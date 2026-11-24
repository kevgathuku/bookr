"""Single booking transaction. Views stay thin: they call book_session()
and map typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402). Waitlist promotion and the hold-expiry sweep
live here too; booking/tasks.py wraps them as shared tasks."""

from contextlib import suppress
from datetime import date, datetime, timedelta
from typing import NoReturn

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking._core import (
    bump_session,
    committed,
    get_session,
    load_open_booking,
    transition_booking,
)
from booking.cancellations import release_unclaimed
from booking.errors import (
    AlreadyCancelled,
    ConcurrentWrite,
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


def _paying_membership(
    *, member: User, session: ClassSession, price: int
) -> Membership:
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


def _validate_membership(
    *, membership: Membership, member: User, session: ClassSession, today: date
) -> None:
    # Mirrors Booking.clean's coherence rules (user-match, org-match) so the
    # service fails fast; the model keeps them for every other write path.
    if membership.user_id != member.pk:
        raise ValidationError("Booking membership belongs to another user.")
    if membership.plan.organization_id != session.offering.venue.organization_id:
        raise ValidationError("Booking plan belongs to another organization.")
    if membership.starts_on > today or (
        membership.valid_until is not None and membership.valid_until < today
    ):
        raise ValidationError("Booking membership is not currently valid.")


def _ensure_open(locked: ClassSession) -> None:
    if locked.cancelled_at is not None:
        raise ValidationError("Session is cancelled.")
    if locked.starts_at <= timezone.now():
        raise ValidationError("Session has already started.")


def _ensure_no_duplicate(*, locked: ClassSession, member: User) -> None:
    if Booking.objects.filter(
        session=locked, member=member, status__in=ACTIVE_STATUSES
    ).exists():
        raise DuplicateBooking(f"{member} already booked {locked}.")


def _is_full(locked: ClassSession) -> bool:
    # Seated bookings and held seats occupy capacity; the queue waits outside it.
    # Race-safe through bump_session: both occupancy-increasing writers
    # (_create_booking via book_session, _seat_head via promote_next) bump
    # the session version before writing, so a stale count retries.
    # Confirm (held->booked) is occupancy-neutral and needs no lock.
    return (
        Booking.objects.filter(
            session=locked, status__in=(Booking.Status.BOOKED, Booking.Status.HELD)
        ).count()
        >= locked.capacity
    )


def _next_waiter(locked: ClassSession) -> Booking | None:
    return (
        Booking.objects.filter(session=locked)
        .filter(status=Booking.Status.WAITLISTED)
        .select_related("member")
        .order_by("created_at", "pk")
        .first()
    )


def _charge_for(*, membership: Membership, price: int, spend_credits: bool) -> int:
    if membership.plan.entitlement == Entitlement.UNLIMITED or not spend_credits:
        return 0
    return price


def _create_booking(
    *, locked: ClassSession, member: User, membership: Membership, amount: int
) -> Booking:
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
    """Book one seat, serialized per session via a version bump.

    Retries are safe through the natural key: the same member + session can
    hold exactly one active booking, so a repeated request raises
    DuplicateBooking instead of double-booking or double-spending.

    Full GROUP sessions queue instead when waitlist=True: a WAITLISTED row
    with no seat and no spend (spend happens on confirm). Private
    sessions never queue: they book or raise SeatFull.
    """
    for _ in range(5):
        # None means another taker moved the session: try again on fresh state.
        booking = _attempt_book(
            session=session,
            member=member,
            membership=membership,
            spend_credits=spend_credits,
            waitlist=waitlist,
        )
        if booking is not None:
            return booking
    raise ConcurrentWrite("Session is under heavy contention; retry the request.")


def _attempt_book(
    *,
    session: ClassSession,
    member: User,
    membership: Membership | None,
    spend_credits: bool,
    waitlist: bool,
) -> Booking | None:
    """One booking attempt: None signals a lost race, the caller retries."""
    try:
        with transaction.atomic():
            locked = get_session(SessionId(session.pk))
            _ensure_open(locked)
            _ensure_no_duplicate(locked=locked, member=member)
            if _is_full(locked):
                return _join_or_refuse(
                    locked=locked,
                    member=member,
                    membership=membership,
                    waitlist=waitlist,
                )
            price = locked.offering.credit_cost
            if membership is None:
                membership = _paying_membership(
                    member=member, session=locked, price=price
                )
            else:
                _validate_membership(
                    membership=membership,
                    member=member,
                    session=locked,
                    today=timezone.now().date(),
                )
            amount = _charge_for(
                membership=membership, price=price, spend_credits=spend_credits
            )
            bump_session(locked)
            booking = _create_booking(
                locked=locked, member=member, membership=membership, amount=amount
            )
            _spend_or_duplicate(
                membership=membership, amount=amount, booking=booking, locked=locked
            )
    except ConcurrentWrite:
        return None
    return booking


def _spend_or_duplicate(
    *, membership: Membership, amount: int, booking: Booking, locked: ClassSession
) -> None:
    try:
        spend_for_booking(membership, amount, booking)
    except IntegrityError:
        # Lost a same-member double-submit race: the winner's spend
        # stands, so this attempt is a duplicate, not a new booking.
        raise DuplicateBooking(f"{booking.member} already booked {locked}.")


def _join_or_refuse(
    *,
    locked: ClassSession,
    member: User,
    membership: Membership | None,
    waitlist: bool,
) -> Booking:
    if not waitlist or locked.offering.category != ClassCategory.GROUP:
        raise SeatFull(f"{locked} is full.")
    # Joining needs a valid membership (org validity is all we check:
    # the credits move at confirm time, never here).
    if membership is None:
        membership = _paying_membership(
            member=member, session=locked, price=locked.offering.credit_cost
        )
    else:
        _validate_membership(
            membership=membership,
            member=member,
            session=locked,
            today=timezone.now().date(),
        )
    # The queue insert validates the snapshot too: a stale read from
    # before a session cancel loses here, and the retry sees the cancel.
    bump_session(locked)
    try:
        return Booking.objects.create(
            session=locked,
            member=member,
            membership=membership,
            credits_spent=0,
            status=Booking.Status.WAITLISTED,
        )
    except IntegrityError:
        # A concurrent join won: same answer as a duplicate request.
        raise DuplicateBooking(f"{member} is already queued for {locked}.")


def promote_next(session: ClassSession, now: datetime | None = None) -> Booking | None:
    """Seat the longest-waiting queued member as Held with a deadline.

    Promotion never spends and never checks passes; the head leaves the
    queue and confirm collects the charge. Natural no-op when full or the
    queue is empty, so retries and concurrent workers are safe.
    """
    moment = now or timezone.now()
    for _ in range(5):
        # A lost race falls through to the next attempt; falling off the
        # loop returns None, the documented no-op.
        with suppress(ConcurrentWrite, AlreadyCancelled):
            return _attempt_promote(session=session, moment=moment)
    return None


def _attempt_promote(*, session: ClassSession, moment: datetime) -> Booking | None:
    """One promotion attempt: races raise, the caller retries."""
    with transaction.atomic():
        locked = get_session(SessionId(session.pk))
        if _is_full(locked):
            return None
        head = _next_waiter(locked)
        if head is None:
            return None
        bump_session(locked)
        return _seat_head(locked=locked, head=head, moment=moment)


def _seat_head(*, locked: ClassSession, head: Booking, moment: datetime) -> Booking:
    # The seated head leaves the queue: the waitlist holds waiters only,
    # so a held seat can never be re-promised from this list. The
    # conditional write rejects a head another worker already seated.
    transition_booking(
        head,
        status=Booking.Status.HELD,
        hold_expires_at=moment + timedelta(minutes=HOLD_WINDOW_MINUTES),
    )
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
        membership, amount = _confirmed_charge(
            actor=actor, session=session, membership=membership
        )
        booking.membership = membership
        booking.credits_spent = amount
        booking.status = Booking.Status.BOOKED
        booking.hold_expires_at = None
        try:
            transition_booking(
                booking,
                membership=membership,
                credits_spent=amount,
                status=booking.status,
                hold_expires_at=None,
            )
        except AlreadyCancelled:
            _raise_for_confirm_conflict(booking)
        spend_for_booking(membership, amount, booking)
    return booking


def _raise_for_confirm_conflict(booking: Booking) -> NoReturn:
    """Map a lost confirm race onto the error a fresh load would raise:
    a confirm means the seat is taken (NotHeld), anything else means
    the hold is gone."""
    booking.refresh_from_db()
    if booking.status == Booking.Status.BOOKED:
        raise NotHeld("Booking holds no confirmable seat.")
    raise AlreadyCancelled("Booking changed under a concurrent writer.")


def _confirmed_charge(
    *, actor: User, session: ClassSession, membership: Membership | None
) -> tuple[Membership, int]:
    """Price a held-seat confirmation: pick or validate the payer."""
    price = session.offering.credit_cost
    if membership is None:
        membership = _paying_membership(member=actor, session=session, price=price)
    else:
        _validate_membership(
            membership=membership,
            member=actor,
            session=session,
            today=timezone.now().date(),
        )
    return membership, _charge_for(
        membership=membership, price=price, spend_credits=True
    )


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
        release_unclaimed(
            booking=booking,
            session=session,
            organization=organization,
            actor=None,
            reason="",
        )
        committed(booking, notify_hold_expired)
    promote_next(session)
    return True
