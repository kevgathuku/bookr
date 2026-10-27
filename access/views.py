import logging
from typing import ClassVar

from django.contrib.auth import get_user_model
from rest_framework import generics, serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.models import AccessEvent, AccessPoint, hash_token
from access.services import decide, grants_total
from organizations.permissions import IsStaff, IsVenueMember

User = get_user_model()
logger = logging.getLogger(__name__)


class ControllerAuthentication(BaseAuthentication):
    """Per-controller token: `Authorization: Token <secret>`."""

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        scheme, _, plaintext = header.partition(" ")
        if scheme != "Token" or not plaintext:
            return None
        try:
            point = AccessPoint.objects.select_related("venue").get(
                api_token_hash=hash_token(plaintext)
            )
        except AccessPoint.DoesNotExist:
            raise AuthenticationFailed("Bad controller token.")
        return None, point

    def authenticate_header(self, request):
        return "Token"


class CheckSerializer(serializers.Serializer):
    access_point = serializers.PrimaryKeyRelatedField(
        queryset=AccessPoint.objects.all()
    )
    member = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


class CheckView(APIView):
    """Read-only door decision. 200 + granted flag; 401 on bad token."""

    authentication_classes: ClassVar[list] = [ControllerAuthentication]
    permission_classes: ClassVar[list] = [AllowAny]

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


class AccessEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessEvent
        fields: ClassVar[list[str]] = [
            "id",
            "access_point",
            "member",
            "granted",
            "reason",
            "booking",
            "occurred_at",
        ]


class RecentEventsView(generics.ListAPIView):
    """Frontdesk reads the venue's recent attempts, newest first."""

    serializer_class = AccessEventSerializer
    permission_classes: ClassVar[list] = [IsVenueMember, IsStaff]

    def get_queryset(self):
        events = AccessEvent.objects.filter(
            access_point__venue=self.request.venue
        ).select_related("access_point", "member", "booking")
        point_id = self.request.query_params.get("access_point")
        if point_id is not None:
            events = events.filter(access_point_id=point_id)
        return events[:100]
