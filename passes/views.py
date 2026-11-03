from typing import ClassVar

from django.db import models, transaction
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.permissions import IsDesk, IsVenueMember, staff_covering
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
        IsVenueMember,
    ]

    def get_queryset(self):
        entries = CreditLedger.objects.select_related("membership", "booking").order_by(
            "-created_at"
        )
        if self._is_staff():
            from organizations.admin_mixins import scoped_venues

            venues = scoped_venues(self.request)
            return entries.filter(
                models.Q(membership__bookings__session__offering__venue__in=venues)
            ).distinct()
        return entries.filter(membership__user=self.request.user)

    def _is_staff(self):
        return staff_covering(self.request, self.request.venue)


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
        ]


class MembershipListView(generics.ListAPIView):
    """Own plan memberships; covering staff may list one member's."""

    serializer_class = MembershipSerializer
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
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
        if not staff_covering(self.request, venue):
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
    with transaction.atomic():
        locked = Membership.objects.select_for_update().get(pk=membership.pk)
        balance = locked.credits_remaining + delta
        if balance < 0:
            raise ValidationError("Adjustment would empty the balance.")
        row = CreditLedger.objects.create(
            membership=locked,
            delta=delta,
            reason=CreditLedger.Reason.ADJUSTMENT,
            note=reason,
            created_by=actor,
        )
        locked.credits_remaining = balance
        locked.save(update_fields=["credits_remaining"])
    return row


class LedgerAdjustView(APIView):
    """Desk goodwill path: move credits with a reason, append-only."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsDesk,
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
