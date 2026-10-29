"""Partner-side booking service: allotment counts, contract cancel."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from aggregators.models import AggregatorBooking
from booking.errors import AllotmentExhausted, DuplicateBooking
from booking.models import Booking
from booking.services import book_seat


def book_partner_seat(partner, klass, external_id):
    """Idempotent allotment-capped booking. Returns (booking, created)."""
    link = (
        AggregatorBooking.objects.select_related("booking")
        .filter(aggregator=partner, external_id=external_id)
        .first()
    )
    if link is not None:
        if link.booking.scheduled_class_id != klass.pk:
            raise DuplicateBooking("external_id already books another class.")
        return link.booking, False
    with transaction.atomic():
        booking = book_seat(
            partner.service_user,
            klass,
            idempotency_key=f"agg-{partner.slug}-{external_id}",
            spend_credits=False,
            source=f"aggregator:{partner.slug}",
        )
        # Count after the seat lock is held: a parallel retry serializes
        # behind us and sees our booking, so the cap holds. Over-limit
        # raises roll this booking back too, freeing the seat.
        held = AggregatorBooking.objects.filter(
            aggregator=partner,
            booking__scheduled_class=klass,
            booking__status=Booking.Status.CONFIRMED,
        ).count()
        if held + 1 > partner.seat_allotment:
            raise AllotmentExhausted("Allotment exhausted.")
        try:
            AggregatorBooking.objects.create(
                aggregator=partner, external_id=external_id, booking=booking
            )
        except IntegrityError:
            link = AggregatorBooking.objects.select_related("booking").get(
                aggregator=partner, external_id=external_id
            )
            return link.booking, False
    return booking, True


def cancel_partner_booking(partner, booking):
    """Cancel with the contract cutoff; never touches member passes."""
    from booking.endings import close_booking

    target = booking.scheduled_class
    if target is None:
        raise ValidationError("Partner bookings target classes.")
    if booking.status not in (
        Booking.Status.CONFIRMED,
        Booking.Status.WAITLISTED,
    ):
        raise ValidationError("Booking is already closed.")
    cutoff = target.starts_at - timedelta(minutes=partner.cancel_cutoff_minutes)
    outcome = "partner_cancel" if timezone.now() <= cutoff else "partner_late_cancel"
    return close_booking(booking, outcome)
