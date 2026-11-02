from datetime import timedelta
from typing import ClassVar

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from organizations.permissions import IsDesk, IsVenueMember
from scheduling.models import ClassOffering, ClassSession
from scheduling.serializers import (
    GenerateSessionsSerializer,
    OfferingSerializer,
    SessionCancelSerializer,
    SessionSerializer,
)

MAX_WINDOW = timedelta(days=31)


def parse_window_bound(value, default):
    if value is None:
        return default
    try:
        parsed = parse_datetime(value)
    except ValueError, TypeError:
        raise serializers.ValidationError("Window bounds must be datetimes.")
    if parsed is None:
        raise serializers.ValidationError("Window bounds must be datetimes.")
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


def _window(request):
    """Shared bounded-window parsing for the new read endpoints."""
    params = request.query_params
    start = parse_window_bound(params.get("from"), timezone.now())
    end = parse_window_bound(params.get("to"), start + MAX_WINDOW)
    if end <= start or end - start > MAX_WINDOW:
        raise serializers.ValidationError("Window must span 1s to 31d.")
    return start, end


class OfferingViewSet(viewsets.ReadOnlyModelViewSet):
    """Venues' offerings. Creation lives in admin (contract owns the form)."""

    serializer_class = OfferingSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def get_queryset(self):
        venue = self.request.venue
        param = self.request.query_params.get("venue")
        if param is not None and param != venue.slug:
            raise NotFound("No such venue.")
        return (
            ClassOffering.objects.filter(venue=venue)
            .select_related("teacher")
            .order_by("title")
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="sessions/generate",
        permission_classes=[IsVenueMember, IsDesk],
    )
    def generate(self, request, pk=None):
        """Expand an RFC recurrence rule into sessions, all or nothing."""
        from scheduling.sessions import generate_sessions

        serializer = GenerateSessionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offering = self.get_object()
        if offering.venue_id != request.venue.pk:
            raise NotFound("No such venue.")
        sessions = generate_sessions(offering=offering, **serializer.validated_data)
        return Response(SessionSerializer(sessions, many=True).data, status=201)


class SessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Bookable sessions with derived ends; cancelled ones never listed."""

    serializer_class = SessionSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]
    filter_backends: ClassVar[list] = [DjangoFilterBackend]  # type: ignore[misc]
    filterset_fields: ClassVar[list[str]] = ["offering__category"]

    def get_queryset(self):
        venue = self.request.venue
        param = self.request.query_params.get("venue")
        if param is not None and param != venue.slug:
            raise NotFound("No such venue.")
        start, end = _window(self.request)
        sessions = ClassSession.objects.for_venue(venue).live()
        return (
            sessions.in_window(start, end)
            .select_related("offering", "offering__teacher")
            .annotate(
                booked=Count(
                    "bookings",
                    filter=Q(bookings__status__in=["booked", "held"]),
                ),
            )
            .order_by("starts_at")
        )

    def get_object(self):
        # Cancel acts on one session regardless of the list window.
        venue = self.request.venue
        session = (
            ClassSession.objects.for_venue(venue)
            .select_related("offering")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if session is None:
            raise NotFound("No such venue.")
        return session

    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
        permission_classes=[IsVenueMember],
    )
    def cancel(self, request, pk=None):
        """Provider-side cancel. The service decides who may: desk any
        session, teachers their own; everyone refunds, none penalized."""
        from booking.cancellations import cancel_session
        from booking.http import mapped_errors
        from booking.serializers import RecordSerializer

        data = SessionCancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = self.get_object()
        with mapped_errors():
            records = cancel_session(
                session_id=session.pk,
                actor=request.user,
                reason=data.validated_data["reason"],
            )
        return Response(RecordSerializer(records, many=True).data)
