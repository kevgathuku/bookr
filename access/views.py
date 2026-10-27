import logging
from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.auth import ControllerAuthentication
from access.models import AccessEvent, AccessPoint
from access.serializers import CheckResultSerializer, CheckSerializer
from access.services import decide, grants_total

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
        granted, reason, booking = self._decide(point, member)
        if reason != "passback_replay":
            self._log(point, member, granted, reason, booking)
        if granted:
            grants_total.labels(venue_id=point.venue_id).inc()
        return Response({"granted": granted, "reason": reason})

    def _decide(self, point, member):
        try:
            return decide(point, member)
        except Exception:  # noqa: BLE001 — any outage denies (fail-closed)
            return False, "system_error", None

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
