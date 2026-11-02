"""Single booking transaction. Views stay thin: they call book_session()
and map typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402). Waitlist promotion and the hold-expiry sweep
live here too; booking/tasks.py wraps them as shared tasks."""

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking.errors import CreditInsufficient, DuplicateBooking, SeatFull
from booking.models import ACTIVE_STATUSES, Booking
from booking.notifications import notify_hold_expired, notify_promoted
from passes.models import CreditLedger, Membership, PlanType
from passes.services import spend_for_booking
from scheduling.models import ClassCategory, ClassSession

# Promotion reserves the seat this long; the sweep releases lapsed holds.
# No per-venue config model exists yet (SPEC §3.2 foresaw one),
# so one explicit constant until a venue asks otherwise.
HOLD_WINDOW_MINUTES = 60


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


def _ensure_no_duplicate(locked, member):
    if Booking.objects.filter(
        session=locked, member=member, status__in=ACTIVE_STATUSES
    ).exists():
        raise DuplicateBooking(f"{member} already booked {locked}.")


def _is_full(locked):
    # Only seated bookings occupy capacity; the queue waits outside it.
    return (
        Booking.objects.filter(session=locked, status=Booking.Status.BOOKED).count()
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


def book_session(
    *, session, member, membership=None, spend_credits=True, waitlist=False
):
    """Book one seat, serialized per session via SELECT ... FOR UPDATE.

    Retries are safe through the natural key: the same member + session can
    hold exactly one active booking, so a repeated request raises
    DuplicateBooking instead of double-booking or double-spending.

    Full GROUP sessions queue instead when waitlist=True: a WAITLISTED row
    with no seat and no spend (spend happens on promotion). Private
    sessions never queue: they book or raise SeatFull.
    """
    with transaction.atomic():
        locked = _lock_session(session)
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
        spend_for_booking(membership, amount, booking)
    return booking


def _join_or_refuse(locked, member, membership, waitlist):
    if not waitlist or locked.offering.category != ClassCategory.GROUP:
        raise SeatFull(f"{locked} is full.")
    # Joining needs a valid membership (org validity is all we check:
    # the credits move at promotion time, never here).
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
    """Promote the longest-waiting queued member into a free seat.

    Spend is written here, never at join; the seat is held until
    hold_expires_at. Natural no-op when full or the queue is empty, so
    retries and concurrent workers are safe. A head whose pass lapsed
    stays queued and the seat stays open.
    """
    moment = now or timezone.now()
    with transaction.atomic():
        locked = _lock_session(session)
        if _is_full(locked):
            return None
        head = _next_waiter(locked)
        if head is None:
            return None
        return _seat_head(locked, head, moment)


def _seat_head(locked, head, moment):
    price = locked.offering.credit_cost
    try:
        membership = _paying_membership(head.member, locked, price)
    except CreditInsufficient:
        return None
    amount = _charge_for(membership, price, True)
    head.membership = membership
    head.credits_spent = amount
    head.status = Booking.Status.BOOKED
    head.hold_expires_at = moment + timedelta(minutes=HOLD_WINDOW_MINUTES)
    head.save(
        update_fields=[
            "membership",
            "credits_spent",
            "status",
            "hold_expires_at",
        ]
    )
    spend_for_booking(membership, amount, head)
    transaction.on_commit(lambda: notify_promoted(head))
    return head


def sweep_expired_holds(now=None):
    """Release lapsed holds: refund the stamp, cancel, seat passes on."""
    moment = now or timezone.now()
    expired = list(
        Booking.objects.filter(status=Booking.Status.BOOKED, hold_expires_at__lt=moment)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    swept = 0
    for pk in expired:
        if _lapse_hold(pk, moment):
            swept += 1
    return swept


def _lapse_hold(pk, moment):
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update().select_related("session").get(pk=pk)
        )
        if (
            booking.status != Booking.Status.BOOKED
            or booking.hold_expires_at is None
            or booking.hold_expires_at >= moment
        ):
            # Member cancelled first, or another worker won the race.
            return False
        stamp = booking.credits_spent
        booking.status = Booking.Status.CANCELLED
        booking.hold_expires_at = None
        booking.save(update_fields=["status", "hold_expires_at"])
        if stamp:
            _refund_stamp(booking)
        transaction.on_commit(lambda: notify_hold_expired(booking, stamp))
    promote_next(booking.session)
    return True


def _refund_stamp(booking):
    # Same lock-then-credit pattern as cancel paths: concurrent refunds
    # of one membership must serialize, or one credit-back is lost.
    membership = Membership.objects.select_for_update().get(pk=booking.membership_id)
    membership.credits_remaining += booking.credits_spent
    membership.save(update_fields=["credits_remaining"])
    CreditLedger.objects.create(
        membership=membership,
        booking=booking,
        delta=booking.credits_spent,
        reason=CreditLedger.Reason.REFUND,
        note=f"waitlist hold lapsed for booking #{booking.pk}",
    )
