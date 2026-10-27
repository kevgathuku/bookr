from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.cancellations import cancel_booking, mark_no_show
from booking.errors import (
    CreditInsufficient,
    DuplicateBooking,
    SeatFull,
    TeacherUnavailable,
)
from booking.http import Conflict, PaymentRequired
from booking.models import Booking
from booking.serializers import BookingSerializer, BookSerializer
from booking.services import book_seat
from organizations.permissions import IsStaff, IsVenueMember, staff_covering


class BookView(APIView):
    """Member booking. Typed service errors map to 409/402 here."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def post(self, request):
        form = BookSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        klass = form.validated_data["scheduled_class"]
        if klass.venue != request.venue:
            raise NotFound("No such venue.")
        try:
            booking = book_seat(
                request.user,
                klass,
                idempotency_key=form.validated_data["idempotency_key"],
                waitlist=form.validated_data["waitlist"],
            )
        except (SeatFull, DuplicateBooking, TeacherUnavailable) as error:
            raise Conflict(str(error))
        except CreditInsufficient as error:
            raise PaymentRequired(str(error))
        return Response(BookingSerializer(booking).data, status=201)


class CancelView(APIView):
    """Owner cancels; staff may override the window with a reason."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def post(self, request, pk):
        booking = self._owned(request, pk)
        override = request.data.get("staff_override") is True
        if override and not staff_covering(request, request.venue):
            raise NotFound("No such venue.")
        if override and not request.data.get("reason"):
            raise ValidationError("Override needs a reason.")
        try:
            booking = cancel_booking(
                request.user,
                booking,
                staff_override=override,
                reason=request.data.get("reason", ""),
            )
        except DjangoValidationError as error:
            raise ValidationError(str(error))
        return Response(BookingSerializer(booking).data)

    def _owned(self, request, pk):
        booking = (
            Booking.objects.filter(pk=pk, venue=request.venue)
            .select_related("scheduled_class", "appointment")
            .first()
        )
        if booking is None:
            raise NotFound("No such venue.")
        if booking.member != request.user and not staff_covering(
            request, request.venue
        ):
            raise NotFound("No such venue.")
        return booking


class NoShowView(APIView):
    """Frontdesk marks a confirmed booking within 2h after the end."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    def post(self, request, pk):
        booking = (
            Booking.objects.filter(pk=pk, venue=request.venue)
            .select_related("scheduled_class", "appointment")
            .first()
        )
        if booking is None:
            raise NotFound("No such venue.")
        try:
            booking = mark_no_show(request.user, booking)
        except DjangoValidationError as error:
            raise ValidationError(str(error))
        return Response(BookingSerializer(booking).data)


class MineView(APIView):
    """Own bookings, newest first."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def get(self, request):
        bookings = Booking.objects.filter(member=request.user).order_by("-created_at")
        return Response(BookingSerializer(bookings, many=True).data)
