from typing import ClassVar

from django.contrib.auth import get_user_model
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.permissions import IsStaffOrReadOnly, IsVenueMember
from organizations.tenancy import STAFF_ROLES, _covers
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
            "booking",
            "delta",
            "reason",
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


class LedgerView(generics.ListAPIView):
    """Own entries for members; whole-venue entries for covering staff."""

    serializer_class = CreditLedgerSerializer
    permission_classes: ClassVar[list] = [IsVenueMember]

    def get_queryset(self):
        entries = CreditLedger.objects.select_related(
            "member_pass", "booking"
        ).order_by("-created_at")
        if self._is_staff():
            return entries.filter(member_pass__product__venue=self.request.venue)
        return entries.filter(member_pass__member=self.request.user)

    def _is_staff(self):
        return any(
            membership.role in STAFF_ROLES and _covers(membership, self.request.venue)
            for membership in getattr(self.request, "memberships", ())
        )


class AdjustView(APIView):
    """Staff correction with mandatory reason. Returns the pass."""

    permission_classes: ClassVar[list] = [IsVenueMember, IsStaffOrReadOnly]

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
