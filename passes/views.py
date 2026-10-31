from typing import ClassVar

from django.contrib.auth import get_user_model
from django.db import models
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.permissions import (
    IsStaff,
    IsStaffOrReadOnly,
    IsVenueMember,
    staff_covering,
)
from passes.models import CreditLedger, MemberPass
from passes.services import adjust_credit

User = get_user_model()


class MemberPassSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = MemberPass
        fields: ClassVar[list[str]] = [
            "id",
            "product",
            "product_name",
            "credits_total",
            "credits_used",
            "valid_from",
            "valid_until",
            "status",
        ]


class CreditLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditLedger
        fields: ClassVar[list[str]] = [
            "id",
            "member_pass",
            "membership",
            "booking",
            "delta",
            "reason",
            "note",
            "created_by",
            "created_at",
        ]


class AdjustSerializer(serializers.Serializer):
    member_pass = serializers.PrimaryKeyRelatedField(queryset=MemberPass.objects.all())
    delta = serializers.IntegerField()
    reason = serializers.CharField(allow_blank=False)

    def validate_delta(self, value):
        if value == 0:
            raise serializers.ValidationError("Delta must be non-zero.")
        return value


class MyPassesView(generics.ListAPIView):
    """Own passes, all venues. Membership alone suffices."""

    serializer_class = MemberPassSerializer

    def get_queryset(self):
        return (
            MemberPass.objects.filter(member=self.request.user)
            .select_related("product")
            .order_by("valid_until")
        )


class MemberPassesView(generics.ListAPIView):
    """Frontdesk lists one member's passes by ?member= id."""

    serializer_class = MemberPassSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    def get_queryset(self):
        member_id = self.request.query_params.get("member")
        return (
            MemberPass.objects.filter(member_id=member_id)
            .select_related("product")
            .order_by("valid_until")
        )


class LedgerView(generics.ListAPIView):
    """Own entries for members; whole-venue entries for covering staff."""

    serializer_class = CreditLedgerSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def get_queryset(self):
        entries = CreditLedger.objects.select_related(
            "member_pass", "membership", "booking"
        ).order_by("-created_at")
        if self._is_staff():
            # Plan rows are org-wide by design (plans have no venue), so
            # venue staff see their venue's pass rows plus the org's plan
            # rows; per-venue partitioning can return in .7 if needed.
            return entries.filter(
                models.Q(member_pass__product__venue=self.request.venue)
                | models.Q(
                    membership__plan__organization=self.request.venue.organization
                )
            )
        return entries.filter(
            models.Q(member_pass__member=self.request.user)
            | models.Q(membership__user=self.request.user)
        )

    def _is_staff(self):
        return staff_covering(self.request, self.request.venue)


class AdjustView(APIView):
    """Staff correction with mandatory reason. Returns the pass."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaffOrReadOnly,
    ]

    @extend_schema(request=AdjustSerializer, responses=MemberPassSerializer)
    def post(self, request):
        form = AdjustSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        member_pass = form.validated_data["member_pass"]
        if member_pass.product.venue != request.venue:
            raise NotFound("No such venue.")
        adjust_credit(
            member_pass,
            form.validated_data["delta"],
            form.validated_data["reason"],
            request.user,
        )
        member_pass.refresh_from_db()
        return Response(MemberPassSerializer(member_pass).data)
