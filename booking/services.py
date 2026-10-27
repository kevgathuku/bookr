"""Single booking transaction. Views stay thin: they call book_seat() and map
these typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402)."""

from collections.abc import Callable

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from booking.errors import DuplicateBooking, SeatFull
from booking.models import ACTIVE_STATUSES, Booking
from scheduling.models import ScheduledClass

User = get_user_model()


def _active_booking(member: User, klass: ScheduledClass) -> bool:
    return Booking.objects.filter(
        venue=klass.venue,
        member=member,
        scheduled_class=klass,
        status__in=ACTIVE_STATUSES,
    ).exists()


def _status_for(klass: ScheduledClass, waitlist: bool) -> str:
    confirmed_seats = Booking.objects.filter(
        scheduled_class=klass,
        status=Booking.Status.CONFIRMED,
    ).count()
    if confirmed_seats < (klass.capacity or 0):
        return Booking.Status.CONFIRMED
    if waitlist:
        return Booking.Status.WAITLISTED
    raise SeatFull(f"{klass} is full.")


def _create(member: User, klass: ScheduledClass, status: str, idem_key: str) -> Booking:
    try:
        return Booking.objects.create(
            venue=klass.venue,
            member=member,
            scheduled_class=klass,
            status=status,
            idempotency_key=idem_key,
        )
    except IntegrityError:
        # Lost a same-key race: the winner's row is the answer.
        winner = Booking.objects.filter(idempotency_key=idem_key).first()
        if winner is not None:
            return winner
        raise DuplicateBooking(f"{member} already booked {klass}.")


def book_seat(
    member: User,
    klass: ScheduledClass,
    *,
    idempotency_key: str,
    waitlist: bool = False,
    spend_credit: Callable[[], None] | None = None,
) -> Booking:
    """Book one seat, serialized per class via SELECT ... FOR UPDATE.

    spend_credit is a stub seam until the passes ticket wires the real ledger:
    called inside the transaction, its return ignored, its
    CreditInsufficient propagated with nothing written.
    """
    with transaction.atomic():
        locked = ScheduledClass.objects.select_for_update().get(pk=klass.pk)

        existing = Booking.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing
        if _active_booking(member, locked):
            raise DuplicateBooking(f"{member} already booked {locked}.")

        status = _status_for(locked, waitlist)
        if spend_credit is not None:
            spend_credit()
        return _create(member, locked, status, idempotency_key)
