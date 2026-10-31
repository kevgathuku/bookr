"""Member booking flows and desk cancel flows on the new graph."""

import datetime
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.cancellations import (
    cancel_booking,
    check_in,
    mark_no_show,
    waive_record,
)
from booking.http import mapped_errors
from booking.models import Booking, CancellationPolicy, CancellationRecord
from booking.serializers import (
    BookingSerializer,
    BookSerializer,
    CancelBookingSerializer,
    PolicySerializer,
    RecordSerializer,
    WaiveSerializer,
)
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
    class_title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    status = serializers.CharField()
    checked_in_at = serializers.DateTimeField(allow_null=True)


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
                        "class_title": booking.session.offering.title,
                        "starts_at": booking.session.starts_at,
                        "status": booking.status,
                        "checked_in_at": booking.checked_in_at,
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


class PolicyListView(generics.ListAPIView):
    """Back-office rule lookup; filterable for the desk UI and coverage."""

    serializer_class = PolicySerializer
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]
    filter_backends: ClassVar[list] = [DjangoFilterBackend]  # type: ignore[misc]
    filterset_fields: ClassVar[list[str]] = [
        "venue",
        "class_category",
        "plan_type",
        "enforcement",
    ]

    def get_queryset(self):
        return CancellationPolicy.objects.filter(
            organization=self.request.venue.organization
        ).order_by("venue", "class_category", "plan_type")


def _record_response(request, pk, call):
    booking = _owned(request, pk)
    with mapped_errors():
        record = call(booking)
    return Response(RecordSerializer(record).data)


class BookingCancelView(APIView):
    """Cancel one booking: member's own choice, or desk on their behalf
    with an explicit reason. Waivers ride along; contradictions raise."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(request=CancelBookingSerializer, responses=RecordSerializer)
    def post(self, request, pk):
        data = CancelBookingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        params = data.validated_data
        return _record_response(
            request,
            pk,
            lambda booking: cancel_booking(
                booking_id=booking.pk,
                actor=request.user,
                on_behalf_of=params["staff_override"],
                waive_penalty=params["waive_penalty"],
                reason=params.get("reason") or "",
            ),
        )


class NoShowView(APIView):
    """Door-observed absence. Door staff only; the service enforces it."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(request=None, responses=RecordSerializer)
    def post(self, request, pk):
        return _record_response(
            request,
            pk,
            lambda booking: mark_no_show(booking_id=booking.pk, actor=request.user),
        )


class CheckInView(APIView):
    """Status-only attendance mark. Door staff only."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(request=None, responses=BookingSerializer)
    def post(self, request, pk):
        booking = _owned(request, pk)
        with mapped_errors():
            booking = check_in(booking_id=booking.pk, actor=request.user)
        return Response(BookingSerializer(booking).data)


class RecordWaiveView(APIView):
    """Retroactive waiver with a required reason. Waive-capable roles only."""

    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(request=WaiveSerializer, responses=RecordSerializer)
    def post(self, request, pk):
        data = WaiveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        record = (
            CancellationRecord.objects.filter(
                pk=pk, organization=request.venue.organization
            )
            .select_related("booking")
            .first()
        )
        if record is None:
            raise NotFound("No such venue.")
        with mapped_errors():
            waive_record(
                record_id=record.pk,
                actor=request.user,
                reason=data.validated_data["reason"],
            )
        record.refresh_from_db()
        return Response(RecordSerializer(record).data)
