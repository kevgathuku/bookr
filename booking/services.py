"""Single booking transaction. Views stay thin: they call book_seat() and map
these typed errors to HTTP (SeatFull/DuplicateBooking → 409,
CreditInsufficient → 402)."""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from booking.errors import DuplicateBooking, SeatFull, TeacherUnavailable
from booking.models import ACTIVE_STATUSES, Booking
from passes.services import spend_credit
from scheduling.models import ScheduledClass


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


def _teacher_clash(klass) -> bool:
    from scheduling.appointments import Appointment

    return Appointment.objects.filter(
        venue=klass.venue,
        teacher=klass.teacher,
        status=Appointment.Status.SCHEDULED,
        starts_at__lt=klass.ends_at,
        ends_at__gt=klass.starts_at,
    ).exists()


def _create(member: User, klass: ScheduledClass, status: str, idem_key: str) -> Booking:
    try:
        booking = Booking.objects.create(
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
    # Spend inside the same transaction: CreditInsufficient rolls back the
    # booking too, so nothing is ever written half-done. Unlimited passes
    # spend nothing and leave credit_tx empty. Waitlisted bookings spend on
    # promotion, not before — no seat, no charge.
    if status == Booking.Status.CONFIRMED:
        booking.credit_tx = spend_credit(member, booking)
        booking.save(update_fields=["credit_tx"])
    return booking


def book_seat(
    member: User,
    klass: ScheduledClass,
    *,
    idempotency_key: str,
    waitlist: bool = False,
) -> Booking:
    """Book one seat, serialized per class via SELECT ... FOR UPDATE."""
    with transaction.atomic():
        locked = ScheduledClass.objects.select_for_update().get(pk=klass.pk)

        existing = Booking.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing
        if _active_booking(member, locked):
            raise DuplicateBooking(f"{member} already booked {locked}.")

        status = _status_for(locked, waitlist)
        if _teacher_clash(locked):
            raise TeacherUnavailable(f"{locked.teacher} is booked elsewhere.")
        return _create(member, locked, status, idempotency_key)
