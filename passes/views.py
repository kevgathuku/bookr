from typing import ClassVar

from django.contrib.auth import get_user_model
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations import permissions
from passes.models import CreditLedger, Membership


class CreditLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditLedger
        fields: ClassVar[list[str]] = [
            "id",
            "membership",
            "booking",
            "delta",
            "reason",
            "note",
            "created_by",
            "created_at",
        ]


class LedgerView(generics.ListAPIView):
    """Own entries for members; entries for members booked at the
    staffer's venues for covering staff."""

    serializer_class = CreditLedgerSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        permissions.IsVenueMember,
    ]

    def get_queryset(self):
        entries = CreditLedger.objects.select_related("membership", "booking").order_by(
            "-created_at"
        )
        if self._is_staff():
            from organizations.admin_mixins import scoped_venues

            venues = scoped_venues(self.request)
            return entries.filter(
                membership__bookings__session__offering__venue__in=venues
            ).distinct()
        return entries.filter(membership__user=self.request.user)

    def _is_staff(self):
        return permissions.staff_covering(self.request, self.request.venue)


class MembershipSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_type = serializers.CharField(source="plan.plan_type", read_only=True)

    class Meta:
        model = Membership
        fields: ClassVar[list[str]] = [
            "id",
            "plan",
            "plan_name",
            "plan_type",
            "credits_remaining",
            "starts_on",
            "valid_until",
            "payment_ref",
        ]


class MembershipListView(generics.ListAPIView):
    """Own plan memberships; covering staff may list one member's."""

    serializer_class = MembershipSerializer
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        permissions.IsVenueMember,
    ]

    def get_queryset(self):
        venue = self.request.venue
        rows = (
            Membership.objects.filter(plan__organization=venue.organization)
            .select_related("plan")
            .order_by("id")
        )
        member_id = self.request.query_params.get("member")
        if member_id is None:
            return rows.filter(user=self.request.user)
        if not permissions.staff_covering(self.request, venue):
            raise NotFound("No such venue.")
        return rows.filter(user_id=member_id)


class AdjustSerializer(serializers.Serializer):
    membership = serializers.PrimaryKeyRelatedField(queryset=Membership.objects.all())
    delta = serializers.IntegerField()
    reason = serializers.CharField()

    def validate_delta(self, value):
        if value == 0:
            raise ValidationError("Delta must move credits.")
        return value

    def validate_reason(self, value):
        if not value.strip():
            raise ValidationError("A reason is required.")
        return value.strip()


def _apply_adjust(actor, membership, delta, reason):
    from booking.errors import CreditInsufficient
    from passes.services import post_entry

    try:
        return post_entry(
            membership,
            delta,
            CreditLedger.Reason.ADJUSTMENT,
            note=reason,
            created_by=actor,
        )
    except CreditInsufficient:
        raise ValidationError("Adjustment would empty the balance.")


class GrantSerializer(serializers.Serializer):
    member = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
    )
    credits = serializers.IntegerField(min_value=1)
    duration_days = serializers.IntegerField(min_value=1, default=30)
    note = serializers.CharField(default="", allow_blank=True)
    incident_key = serializers.CharField(max_length=100)


class LedgerGrantView(APIView):
    """Desk grant flow: mint one goodwill membership, idempotent per key."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        permissions.IsVenueMember,
        permissions.IsDesk,
    ]

    def post(self, request):
        from passes.services import grant_goodwill

        form = GrantSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        membership, created = grant_goodwill(
            organization=request.venue.organization,
            user=form.validated_data["member"],
            credits=form.validated_data["credits"],
            duration_days=form.validated_data["duration_days"],
            note=form.validated_data["note"],
            created_by=request.user,
            incident_key=form.validated_data["incident_key"],
        )
        return Response(
            MembershipSerializer(membership).data,
            status=201 if created else 200,
        )


class LedgerAdjustView(APIView):
    """Desk corrections path: fix a balance with a reason, append-only.

    Positive deltas here are corrections only — grants mint a new
    membership through the grants endpoint (one purchase = one membership)."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        permissions.IsVenueMember,
        permissions.IsDesk,
    ]

    def post(self, request):
        form = AdjustSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        membership = form.validated_data["membership"]
        if membership.plan.organization_id != request.venue.organization_id:
            raise NotFound("No such venue.")
        row = _apply_adjust(
            request.user,
            membership,
            form.validated_data["delta"],
            form.validated_data["reason"],
        )
        return Response(CreditLedgerSerializer(row).data, status=201)
