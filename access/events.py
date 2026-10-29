from typing import ClassVar

from rest_framework import generics

from access.models import AccessEvent
from access.serializers import AccessEventSerializer
from organizations.permissions import IsStaff, IsVenueMember


class RecentEventsView(generics.ListAPIView):
    """Frontdesk reads the venue's recent attempts, newest first."""

    serializer_class = AccessEventSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    def get_queryset(self):
        events = AccessEvent.objects.filter(
            access_point__venue=self.request.venue
        ).select_related("access_point", "member", "booking")
        point_id = self.request.query_params.get("access_point")
        if point_id is not None:
            events = events.filter(access_point_id=point_id)
        return events[:100]
