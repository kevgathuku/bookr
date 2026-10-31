"""Partner-side booking service: allotment counts, contract cancel."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from aggregators.models import AggregatorBooking
from booking.errors import AllotmentExhausted, DuplicateBooking
from booking.models import ACTIVE_STATUSES, Booking
from booking.services import book_session
from passes.models import Membership, MembershipPlan, PlanType


def _comp_membership(partner, organization):
    """The pass-free membership partner seats book through."""
    plan, _ = MembershipPlan.objects.get_or_create(
        organization=organization,
        name="Aggregator complimentary",
        defaults={"plan_type": PlanType.COMPLIMENTARY, "validity_days": 365},
    )
    membership, _ = Membership.objects.get_or_create(
        user=partner.service_user,
        plan=plan,
        defaults={
            "credits_remaining": 0,
            "starts_on": timezone.now().date(),
            "ends_on": timezone.now().date() + timedelta(days=365),
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
        membership = _comp_membership(partner, session.offering.venue.organization)
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
    """Cancel with the contract cutoff; never touches member passes."""
    target = booking.session
    if booking.status != Booking.Status.BOOKED:
        raise ValidationError("Booking is already closed.")
    cutoff = target.starts_at - timedelta(minutes=partner.cancel_cutoff_minutes)
    late = timezone.now() > cutoff
    with transaction.atomic():
        locked = Booking.objects.select_for_update(of=("self",)).get(pk=booking.pk)
        if locked.status != Booking.Status.BOOKED:
            raise ValidationError("Booking is already closed.")
        locked.status = (
            Booking.Status.LATE_CANCELLED if late else Booking.Status.CANCELLED
        )
        locked.save(update_fields=["status"])
    return locked
