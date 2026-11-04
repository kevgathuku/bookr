"""Partner-side booking service: allotment counts, contract cancel."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from aggregators.models import AggregatorBooking
from booking.errors import AllotmentExhausted, DuplicateBooking
from booking.models import ACTIVE_STATUSES, Booking
from booking.services import book_session
from common.ids import BookingId
from passes.models import Entitlement, Membership, Plan, PlanType, Validity


def _partner_membership(partner, organization):
    """The pass-free membership partner seats book through."""
    plan, _ = Plan.objects.get_or_create(
        organization=organization,
        plan_type=PlanType.AGGREGATOR,
        defaults={
            "name": "Aggregator allotment",
            "entitlement": Entitlement.UNLIMITED,
            "validity": Validity.OPEN_ENDED,
            "duration_days": None,
        },
    )
    membership, _ = Membership.objects.get_or_create(
        user=partner.service_user,
        plan=plan,
        defaults={
            "credits_remaining": None,
            "starts_on": timezone.now().date(),
            "valid_until": None,
        },
    )
    return membership


def book_partner_seat(partner, session, external_id):
    """Idempotent allotment-capped booking. Returns (booking, created)."""
    link = (
        AggregatorBooking.objects.select_related("booking")
        .filter(aggregator=partner, external_id=external_id)
        .first()
    )
    if link is not None:
        if link.booking.session_id != session.pk:
            raise DuplicateBooking("external_id already books another session.")
        return link.booking, False
    with transaction.atomic():
        membership = _partner_membership(partner, session.offering.venue.organization)
        booking = book_session(
            session=session,
            member=partner.service_user,
            membership=membership,
            spend_credits=False,
        )
        # Count after the seat lock is held: a parallel retry serializes
        # behind us and sees our booking, so the cap holds. Over-limit
        # raises roll this booking back too, freeing the seat.
        held = AggregatorBooking.objects.filter(
            aggregator=partner,
            booking__session=session,
            booking__status__in=ACTIVE_STATUSES,
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
    """Cancel with the contract cutoff; never touches member passes.

    Delegates the transition to cancel_booking so every partner cancel
    leaves the same unified record; the contract cutoff only annotates
    the reason."""
    from booking.cancellations import cancel_booking

    target = booking.session
    if booking.status != Booking.Status.BOOKED:
        raise ValidationError("Booking is already closed.")
    cutoff = target.starts_at - timedelta(minutes=partner.cancel_cutoff_minutes)
    late = timezone.now() > cutoff
    window = "inside" if late else "outside"
    record = cancel_booking(
        booking_id=BookingId(booking.pk),
        actor=booking.member,
        now=timezone.now(),
        reason=f"partner {partner.slug} cancel ({window} contract cutoff)",
    )
    record.booking.refresh_from_db()
    return record.booking
