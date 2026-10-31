from typing import ClassVar

from django.db import models
from rest_framework import generics, serializers

from organizations.permissions import IsVenueMember
from passes.models import CreditLedger


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
        from organizations.permissions import staff_covering

        return staff_covering(self.request, self.request.venue)
