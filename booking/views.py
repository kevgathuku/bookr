"""Member booking flows on the new graph. Cancel/no-show/check-in live in
their own tickets (.4/.6/.10); this module only books and lists."""

import datetime
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.http import mapped_errors
from booking.models import Booking
from booking.serializers import BookingSerializer, BookSerializer
from booking.services import book_session
from organizations.permissions import IsStaff, IsVenueMember, staff_covering


class BookingsView(APIView):
    """POST books a session; GET lists mine (?mine=true)."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(
        responses=BookingSerializer(many=True),
        parameters=[OpenApiParameter("mine", str)],
    )
    def get(self, request):
        if request.query_params.get("mine") != "true":
            raise ValidationError("Only ?mine=true is supported.")
        bookings = Booking.objects.filter(member=request.user).order_by("-created_at")
        return Response(BookingSerializer(bookings, many=True).data)

    @extend_schema(request=BookSerializer, responses=BookingSerializer)
    def post(self, request):
        if request.query_params.get("waitlist") == "true":
            # Waitlists return with the waitlist follow-up; fail loudly
            # instead of silently booking past a full class.
            raise ValidationError("Waitlists are not currently offered.")
        form = BookSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        session = form.validated_data["session"]
        if session.offering.venue != request.venue:
            raise NotFound("No such venue.")
        try:
            with mapped_errors():
                booking = book_session(member=request.user, session=session)
        except DjangoValidationError as error:
            raise ValidationError(str(error))
        return Response(BookingSerializer(booking).data, status=201)


class RosterRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member = serializers.CharField()
    session_title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    status = serializers.CharField()


class RosterView(APIView):
    """Frontdesk day roster: venue bookings with member + session info."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    @extend_schema(
        responses=RosterRowSerializer(many=True),
        parameters=[OpenApiParameter("date", str, required=False)],
    )
    def get(self, request):
        target = request.query_params.get("date")
        try:
            day = (
                datetime.date.fromisoformat(target) if target else timezone.localdate()
            )
        except ValueError:
            raise ValidationError("date must be YYYY-MM-DD.")
        rows = (
            Booking.objects.filter(
                session__offering__venue=request.venue,
                session__starts_at__date=day,
            )
            .select_related("member", "session__offering")
            .order_by("session__starts_at")
        )
        return Response(
            RosterRowSerializer(
                [
                    {
                        "id": booking.pk,
                        "member": booking.member.username,
                        "session_title": booking.session.offering.title,
                        "starts_at": booking.session.starts_at,
                        "status": booking.status,
                    }
                    for booking in rows
                ],
                many=True,
            ).data
        )


class MineView(APIView):
    """Own bookings, newest first."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(responses=BookingSerializer(many=True))
    def get(self, request):
        bookings = Booking.objects.filter(member=request.user).order_by("-created_at")
        return Response(BookingSerializer(bookings, many=True).data)


def _owned(request, pk):
    booking = (
        Booking.objects.filter(pk=pk, session__offering__venue=request.venue)
        .select_related("session", "session__offering")
        .first()
    )
    if booking is None:
        raise NotFound("No such venue.")
    if booking.member != request.user and not staff_covering(request, request.venue):
        raise NotFound("No such venue.")
    return booking
