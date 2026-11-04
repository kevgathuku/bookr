"""Single booking transaction. Views stay thin: they call book_session()
and map typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402). Waitlist promotion and the hold-expiry sweep
live here too; booking/tasks.py wraps them as shared tasks."""

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking._core import committed, load_open_booking, lock_session
from booking.cancellations import release_unclaimed
from booking.errors import (
    AlreadyCancelled,
    CreditInsufficient,
    DuplicateBooking,
    NotHeld,
    SeatFull,
)
from booking.models import ACTIVE_STATUSES, Booking
from booking.notifications import notify_hold_expired, notify_promoted
from common.ids import BookingId, OrgId, SessionId
from passes.models import Entitlement, Membership
from passes.services import spend_for_booking, valid_memberships
from scheduling.models import ClassCategory, ClassSession

# Promotion reserves the seat this long; the sweep releases lapsed holds.
# No per-venue config model exists yet (SPEC §3.2 foresaw one),
# so one explicit constant until a venue asks otherwise.
HOLD_WINDOW_MINUTES = 60


def _paying_membership(member, session, price):
    """Unlimited first, else first-expiring credit pack that covers the price."""
    today = timezone.now().date()
    organization_id = OrgId(session.offering.venue.organization_id)
    candidates = list(valid_memberships(member, organization_id, today))
    unlimited = next(
        (mem for mem in candidates if mem.plan.entitlement == Entitlement.UNLIMITED),
        None,
    )
    if unlimited is not None:
        return unlimited
    for membership in candidates:
        if (
            membership.credits_remaining is not None
            and membership.credits_remaining >= price
        ):
            return membership
    raise CreditInsufficient("No valid membership covers this booking.")


def _validate_membership(membership, member, session, today):
    if membership.user_id != member.pk:
        raise ValidationError("Booking membership belongs to another user.")
    if membership.plan.organization_id != session.offering.venue.organization_id:
        raise ValidationError("Booking plan belongs to another organization.")
    if membership.starts_on > today or (
        membership.valid_until is not None and membership.valid_until < today
    ):
        raise ValidationError("Booking membership is not currently valid.")


def _ensure_open(locked):
    if locked.cancelled_at is not None:
        raise ValidationError("Session is cancelled.")
    if locked.starts_at <= timezone.now():
        raise ValidationError("Session has already started.")


def _ensure_no_duplicate(locked, member):
    if Booking.objects.filter(
        session=locked, member=member, status__in=ACTIVE_STATUSES
    ).exists():
        raise DuplicateBooking(f"{member} already booked {locked}.")


def _is_full(locked):
    # Seated bookings and held seats occupy capacity; the queue waits outside it.
    return (
        Booking.objects.filter(
            session=locked, status__in=(Booking.Status.BOOKED, Booking.Status.HELD)
        ).count()
        >= locked.capacity
    )


def _next_waiter(locked):
    return (
        Booking.objects.select_for_update()
        .filter(session=locked, status=Booking.Status.WAITLISTED)
        .select_related("member")
        .order_by("created_at", "pk")
        .first()
    )


def _charge_for(membership, price, spend_credits):
    if membership.plan.entitlement == Entitlement.UNLIMITED or not spend_credits:
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


def book_session(
    *,
    session: ClassSession,
    member: User,
    membership: Membership | None = None,
    spend_credits: bool = True,
    waitlist: bool = False,
) -> Booking:
    """Book one seat, serialized per session via SELECT ... FOR UPDATE.

    Retries are safe through the natural key: the same member + session can
    hold exactly one active booking, so a repeated request raises
    DuplicateBooking instead of double-booking or double-spending.

    Full GROUP sessions queue instead when waitlist=True: a WAITLISTED row
    with no seat and no spend (spend happens on confirm). Private
    sessions never queue: they book or raise SeatFull.
    """
    with transaction.atomic():
        locked = lock_session(SessionId(session.pk))
        _ensure_open(locked)
        _ensure_no_duplicate(locked, member)
        if _is_full(locked):
            return _join_or_refuse(locked, member, membership, waitlist)
        price = locked.offering.credit_cost
        if membership is None:
            membership = _paying_membership(member, locked, price)
        else:
            _validate_membership(membership, member, locked, timezone.now().date())
        amount = _charge_for(membership, price, spend_credits)
        booking = _create_booking(locked, member, membership, amount)
        try:
            spend_for_booking(membership, amount, booking)
        except IntegrityError:
            # Lost a same-member double-submit race: the winner's spend
            # stands, so this attempt is a duplicate, not a new booking.
            raise DuplicateBooking(f"{member} already booked {locked}.")
    return booking


def _join_or_refuse(locked, member, membership, waitlist):
    if not waitlist or locked.offering.category != ClassCategory.GROUP:
        raise SeatFull(f"{locked} is full.")
    # Joining needs a valid membership (org validity is all we check:
    # the credits move at confirm time, never here).
    if membership is None:
        membership = _paying_membership(member, locked, locked.offering.credit_cost)
    else:
        _validate_membership(membership, member, locked, timezone.now().date())
    return Booking.objects.create(
        session=locked,
        member=member,
        membership=membership,
        credits_spent=0,
        status=Booking.Status.WAITLISTED,
    )


def promote_next(session: ClassSession, now: datetime | None = None) -> Booking | None:
    """Seat the longest-waiting queued member as Held with a deadline.

    Promotion never spends and never checks passes; the head leaves the
    queue and confirm collects the charge. Natural no-op when full or the
    queue is empty, so retries and concurrent workers are safe.
    """
    moment = now or timezone.now()
    with transaction.atomic():
        locked = lock_session(SessionId(session.pk))
        if _is_full(locked):
            return None
        head = _next_waiter(locked)
        if head is None:
            return None
        return _seat_head(locked, head, moment)


def _seat_head(locked, head, moment):
    # The seated head leaves the queue: the waitlist holds waiters only,
    # so a held seat can never be re-promised from this list.
    head.status = Booking.Status.HELD
    head.hold_expires_at = moment + timedelta(minutes=HOLD_WINDOW_MINUTES)
    head.save(update_fields=["status", "hold_expires_at"])
    return committed(head, notify_promoted)


def confirm_booking(
    *, booking_id: BookingId, actor: User, membership: Membership | None = None
) -> Booking:
    """Claim a held seat: charge the pass, flip Held to Booked."""
    with transaction.atomic():
        loaded = load_open_booking(BookingId(booking_id), timezone.now())
        booking, session = loaded.booking, loaded.session
        if booking.status != Booking.Status.HELD:
            raise NotHeld("Booking holds no confirmable seat.")
        if booking.hold_expires_at is None or booking.hold_expires_at <= timezone.now():
            raise NotHeld("The hold has expired; the seat is released.")
        if booking.member_id != actor.pk:
            raise PermissionDenied("Only the holding member can confirm.")
        _ensure_open(session)
        membership, amount = _confirmed_charge(actor, session, membership)
        booking.membership = membership
        booking.credits_spent = amount
        booking.status = Booking.Status.BOOKED
        booking.hold_expires_at = None
        booking.save(
            update_fields=[
                "membership",
                "credits_spent",
                "status",
                "hold_expires_at",
            ]
        )
        spend_for_booking(membership, amount, booking)
    return booking


def _confirmed_charge(actor, session, membership):
    """Price a held-seat confirmation: pick or validate the payer."""
    price = session.offering.credit_cost
    if membership is None:
        membership = _paying_membership(actor, session, price)
    else:
        _validate_membership(membership, actor, session, timezone.now().date())
    return membership, _charge_for(membership, price, True)


def sweep_expired_holds(now: datetime | None = None) -> int:
    """Release lapsed holds as unclaimed; each freed seat passes on."""
    moment = now or timezone.now()
    expired = list(
        Booking.objects.filter(status=Booking.Status.HELD, hold_expires_at__lte=moment)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    swept = 0
    for pk in expired:
        if _lapse_hold(BookingId(pk), moment):
            swept += 1
    return swept


def _lapse_hold(pk: BookingId, moment: datetime) -> bool:
    with transaction.atomic():
        try:
            loaded = load_open_booking(BookingId(pk), moment, allow_started=True)
        except AlreadyCancelled:
            # Member cancelled first, or another worker won.
            return False
        booking, session = loaded.booking, loaded.session
        organization = loaded.venue.organization
        if (
            booking.status != Booking.Status.HELD
            or booking.hold_expires_at is None
            or booking.hold_expires_at > moment
        ):
            # Member confirmed first, or another worker won.
            return False
        release_unclaimed(booking, session, organization, None, "")
        committed(booking, notify_hold_expired)
    promote_next(session)
    return True
