from celery import shared_task
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking import notify
from booking.endings import spend_for_confirmation
from booking.errors import CreditInsufficient
from booking.models import Booking


def _free_seat(locked):
    confirmed = Booking.objects.filter(
        scheduled_class=locked, status=Booking.Status.CONFIRMED
    ).count()
    return confirmed < (locked.capacity or 0)


def _promote(first):
    try:
        spend_for_confirmation(first)
    except CreditInsufficient:
        return 0  # pass lapsed while waiting: stays queued, seat stays open
    minutes = first.venue.policy_for(first.member).waitlist_hold_minutes
    first.status = Booking.Status.CONFIRMED
    first.hold_until = timezone.now() + timezone.timedelta(minutes=minutes)
    first.save(update_fields=["status", "hold_until"])
    notify.booking_promoted(first)
    return 1


@shared_task(name="booking.promote_waitlist")
def promote_waitlist(class_id):
    """Promote the longest-waiting waiter into a free seat. Natural no-op
    when full or empty, so retries are safe."""
    from scheduling.models import ScheduledClass

    with transaction.atomic():
        locked = ScheduledClass.objects.select_for_update().get(pk=class_id)
        if not _free_seat(locked):
            return 0
        first = (
            Booking.objects.select_for_update()
            .filter(scheduled_class=locked, status=Booking.Status.WAITLISTED)
            .order_by("created_at")
            .first()
        )
        if first is None:
            return 0
        return _promote(first)


@shared_task(name="booking.sweep_expired_holds")
def sweep_expired_holds():
    """Beat sweeper: lapsed holds cancel and the seat passes to next."""
    from booking.endings import close_booking

    now = timezone.now()
    swept = 0
    held = Booking.objects.filter(
        status=Booking.Status.CONFIRMED, hold_until__lt=now
    ).select_related("scheduled_class")
    for booking in held:
        try:
            close_booking(booking, "hold_lapsed")
        except ValidationError:
            continue  # member cancelled first, or another worker won the race
        swept += 1
    return swept
