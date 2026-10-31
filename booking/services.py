"""Single booking transaction. Views stay thin: they call book_session()
and map typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402)."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking.errors import CreditInsufficient, DuplicateBooking, SeatFull
from booking.models import ACTIVE_STATUSES, Booking
from passes.models import Membership, PlanType
from passes.services import spend_for_booking
from scheduling.catalogue import ClassSession


def _valid_memberships(member, organization_id, today):
    return (
        Membership.objects.filter(
            user=member,
            plan__organization_id=organization_id,
            starts_on__lte=today,
        )
        .filter(ends_on__gte=today)
        .select_related("plan")
        .order_by("starts_on")
    )


def _paying_membership(member, session, price):
    """Monthly-valid first, else oldest credit pack that covers the price."""
    today = timezone.now().date()
    organization_id = session.offering.venue.organization_id
    candidates = list(_valid_memberships(member, organization_id, today))
    monthly = next(
        (mem for mem in candidates if mem.plan.plan_type == PlanType.MONTHLY),
        None,
    )
    if monthly is not None:
        return monthly
    for membership in candidates:
        if membership.credits_remaining >= price:
            return membership
    raise CreditInsufficient("No valid membership covers this booking.")


def _validate_membership(membership, member, session, today):
    if membership.user_id != member.pk:
        raise ValidationError("Booking membership belongs to another user.")
    if membership.plan.organization_id != session.offering.venue.organization_id:
        raise ValidationError("Booking plan belongs to another organization.")
    if membership.starts_on > today or membership.ends_on < today:
        raise ValidationError("Booking membership is not currently valid.")


def _lock_session(session):
    return (
        ClassSession.objects.select_for_update()
        .select_related("offering", "offering__venue")
        .get(pk=session.pk)
    )


def _ensure_open(locked):
    if locked.cancelled_at is not None:
        raise ValidationError("Session is cancelled.")
    if locked.starts_at <= timezone.now():
        raise ValidationError("Session has already started.")


def _ensure_seat(locked, member):
    active = Booking.objects.filter(
        session=locked, member=member, status__in=ACTIVE_STATUSES
    )
    if active.exists():
        raise DuplicateBooking(f"{member} already booked {locked}.")
    if (
        Booking.objects.filter(session=locked, status__in=ACTIVE_STATUSES).count()
        >= locked.capacity
    ):
        raise SeatFull(f"{locked} is full.")


def _charge_for(membership, price, spend_credits):
    if membership.plan.plan_type == PlanType.MONTHLY or not spend_credits:
        return 0
    return price


def _create_booking(locked, member, membership, amount):
    try:
        return Booking.objects.create(
            session=locked,
            member=member,
            membership=membership,
            credits_spent=amount,
        )
    except IntegrityError:
        # Lost a same-seat race: the winner's row is the answer.
        winner = Booking.objects.filter(
            session=locked, member=member, status__in=ACTIVE_STATUSES
        ).first()
        if winner is None:
            raise DuplicateBooking(f"{member} already booked {locked}.")
        return winner


def book_session(*, session, member, membership=None, spend_credits=True):
    """Book one seat, serialized per session via SELECT ... FOR UPDATE.

    Retries are safe through the natural key: the same member + session can
    hold exactly one active booking, so a repeated request raises
    DuplicateBooking instead of double-booking or double-spending.
    """
    with transaction.atomic():
        locked = _lock_session(session)
        _ensure_open(locked)
        _ensure_seat(locked, member)
        price = locked.offering.credit_cost
        if membership is None:
            membership = _paying_membership(member, locked, price)
        else:
            _validate_membership(membership, member, locked, timezone.now().date())
        amount = _charge_for(membership, price, spend_credits)
        booking = _create_booking(locked, member, membership, amount)
        spend_for_booking(membership, amount, booking)
    return booking
