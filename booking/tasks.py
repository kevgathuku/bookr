from celery import shared_task
from django.db import transaction
from django.utils import timezone

from booking import notify
from booking.errors import CreditInsufficient
from booking.models import Booking
from passes.services import refund_credit, spend_credit


def _free_seat(locked):
    confirmed = Booking.objects.filter(
        scheduled_class=locked, status=Booking.Status.CONFIRMED
    ).count()
    return confirmed < (locked.capacity or 0)


def _promote(first):
    try:
        ledger = spend_credit(first.member, first)
    except CreditInsufficient:
        return 0  # pass lapsed while waiting: stays queued, seat stays open
    minutes = first.venue.current_policy.waitlist_hold_minutes
    first.credit_tx = ledger
    first.status = Booking.Status.CONFIRMED
    first.hold_until = timezone.now() + timezone.timedelta(minutes=minutes)
    first.save(update_fields=["credit_tx", "status", "hold_until"])
    notify.booking_promoted(first)
    return 1


@shared_task(name="booking.promote_waitlist")
def promote_waitlist(booking_id=None, class_id=None):
    """Promote the longest-waiting waiter into a free seat. Natural no-op
    when full or empty, so retries are safe."""
    from scheduling.models import ScheduledClass

    if (booking_id is None) == (class_id is None):
        raise ValueError("Pass exactly one of booking_id, class_id.")
    if class_id is None:
        trigger = Booking.objects.select_related("scheduled_class").get(pk=booking_id)
        class_id = trigger.scheduled_class_id
        if class_id is None:
            return 0
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
    now = timezone.now()
    swept = 0
    held = Booking.objects.filter(
        status=Booking.Status.CONFIRMED, hold_until__lt=now
    ).select_related("scheduled_class")
    for booking in held:
        with transaction.atomic():
            locked = Booking.objects.select_for_update().get(pk=booking.pk)
            if locked.status != Booking.Status.CONFIRMED or (
                locked.hold_until is not None and locked.hold_until >= now
            ):
                continue
            refund_credit(locked)
            locked.status = Booking.Status.CANCELLED
            locked.hold_until = None
            locked.save(update_fields=["status", "hold_until"])
            swept += 1
            if locked.scheduled_class_id is not None:
                promote_waitlist.delay(class_id=locked.scheduled_class_id)
    return swept
