import logging
from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.auth import ControllerAuthentication
from access.models import AccessEvent, AccessPoint
from access.serializers import (
    AccessEventSerializer,
    CheckResultSerializer,
    CheckSerializer,
)
from access.services import DoorVerdict, decide
from organizations.permissions import IsStaff, IsVenueMember

logger = logging.getLogger(__name__)


class CheckView(APIView):
    """Read-only door decision. 200 + granted flag; 401 on bad token."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    authentication_classes: ClassVar[list] = [  # type: ignore[misc]
        ControllerAuthentication,
    ]
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        AllowAny,
    ]

    @extend_schema(request=CheckSerializer, responses=CheckResultSerializer)
    def post(self, request):
        form = CheckSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        point = form.validated_data["access_point"]
        member = form.validated_data["member"]
        if isinstance(request.auth, AccessPoint) and request.auth != point:
            raise NotFound("No such venue.")
        return self._verdict(point, member)

    def _verdict(self, point, member):
        verdict = self._decide(point, member)
        if verdict.reason != "passback_replay":
            self._log(point, member, verdict.granted, verdict.reason, verdict.booking)
        return Response({"granted": verdict.granted, "reason": verdict.reason})

    def _decide(self, point, member):
        try:
            return decide(point, member)
        except Exception:  # noqa: BLE001 — any outage denies (fail-closed)
            return DoorVerdict(granted=False, reason="system_error", booking=None)

    def _log(self, point, member, granted, reason, booking):
        try:
            AccessEvent.objects.create(
                access_point=point,
                member=member,
                granted=granted,
                reason=reason,
                booking=booking,
            )
        except Exception:  # log best-effort; deny stands
            logger.warning("access event log failed", exc_info=True)


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
