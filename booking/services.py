"""Single booking transaction. Views stay thin: they call book_seat() and map
these typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402)."""

from collections.abc import Callable

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from booking.models import Booking
from scheduling.models import ScheduledClass

User = get_user_model()


class BookingError(Exception):
    """Base for all book_seat() failures."""


class SeatFull(BookingError):
    """Class is full and waitlist was not requested."""


class CreditInsufficient(BookingError):
    """Member has no spendable credit for this booking."""


class DuplicateBooking(BookingError):
    """Member already holds an active booking for this class."""


def book_seat(
    member: User,
    klass: ScheduledClass,
    *,
    idempotency_key: str,
    waitlist: bool = False,
    source: str = "app",
    spend_credit: Callable[[], None] | None = None,
) -> Booking:
    """Book one seat, serialized per class via SELECT ... FOR UPDATE.

    spend_credit is a stub seam until the passes ticket wires the real ledger:
    called inside the transaction, its return ignored, its
    CreditInsufficient propagated with nothing written.
    """
    with transaction.atomic():
        klass = ScheduledClass.objects.select_for_update().get(pk=klass.pk)

        existing = Booking.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

        if Booking.objects.filter(
            venue=klass.venue,
            member=member,
            scheduled_class=klass,
            status__in=Booking.ACTIVE,
        ).exists():
            raise DuplicateBooking(f"{member} already booked {klass}.")

        status = Booking.Status.CONFIRMED
        if Booking.objects.filter(
            scheduled_class=klass, status=Booking.Status.CONFIRMED
        ).count() >= (klass.capacity or 0):
            if not waitlist:
                raise SeatFull(f"{klass} is full.")
            status = Booking.Status.WAITLISTED

        if spend_credit is not None:
            spend_credit()

        try:
            return Booking.objects.create(
                venue=klass.venue,
                member=member,
                scheduled_class=klass,
                status=status,
                source=source,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            # Lost a same-key race: the winner's row is the answer.
            winner = Booking.objects.filter(idempotency_key=idempotency_key).first()
            if winner is not None:
                return winner
            raise DuplicateBooking(f"{member} already booked {klass}.")
