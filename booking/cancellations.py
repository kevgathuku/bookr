"""Endings: member cancel under window rules, staff override, no-show, bars."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking import notify
from booking.models import Booking
from passes.services import refund_credit


def _window_hours(booking):
    policy = booking.venue.current_policy
    if booking.scheduled_class_id is not None:
        return policy.class_late_cancel_hours
    return policy.appointment_late_cancel_hours


def _target(booking):
    return booking.scheduled_class or booking.appointment


def cancel_booking(actor, booking, *, staff_override=False, reason=""):
    """Cancel inside a transaction; frees the seat and triggers promotion."""
    with transaction.atomic():
        locked = (
            Booking.objects.select_for_update(of=("self",))
            .select_related("scheduled_class", "appointment", "venue")
            .get(pk=booking.pk)
        )
        if locked.status not in (
            Booking.Status.CONFIRMED,
            Booking.Status.WAITLISTED,
        ):
            raise ValidationError("Booking is already closed.")
        freed = locked.status == Booking.Status.CONFIRMED
        if staff_override:
            refund_credit(locked)
            locked.status = Booking.Status.CANCELLED
        else:
            target = _target(locked)
            cutoff = target.starts_at - timedelta(hours=_window_hours(locked))
            if timezone.now() <= cutoff:
                refund_credit(locked)
                locked.status = Booking.Status.CANCELLED
                notify.booking_cancelled(locked)
            else:
                locked.status = Booking.Status.CANCELLED_LATE
                notify.booking_late_cancel(locked)
        locked.save(update_fields=["status"])
        if freed and locked.scheduled_class_id is not None:
            from booking.tasks import promote_waitlist

            promote_waitlist.delay(booking_id=locked.pk)
    return locked


def check_in(actor, booking):
    """Frontdesk stamps a confirmed booking as checked in."""
    with transaction.atomic():
        locked = (
            Booking.objects.select_for_update(of=("self",))
            .select_related("scheduled_class", "appointment")
            .get(pk=booking.pk)
        )
        if locked.status != Booking.Status.CONFIRMED:
            raise ValidationError("Only confirmed bookings can check in.")
        locked.checked_in_at = timezone.now()
        locked.save(update_fields=["checked_in_at"])
    return locked


def mark_no_show(actor, booking):
    """Frontdesk marks a confirmed booking within 2h after end. Forfeits."""
    with transaction.atomic():
        locked = (
            Booking.objects.select_for_update(of=("self",))
            .select_related("scheduled_class", "appointment")
            .get(pk=booking.pk)
        )
        if locked.status != Booking.Status.CONFIRMED:
            raise ValidationError("Only confirmed bookings can no-show.")
        target = _target(locked)
        now = timezone.now()
        if not target.ends_at <= now <= target.ends_at + timedelta(hours=2):
            raise ValidationError("No-show window is 2h after the end.")
        locked.status = Booking.Status.NO_SHOW
        locked.save(update_fields=["status"])
        if locked.scheduled_class_id is not None:
            from booking.tasks import promote_waitlist

            promote_waitlist.delay(booking_id=locked.pk)
    return locked


def has_strike_flag(member):
    """3+ late-cancels/no-shows on recent targets: flag, never auto-ban."""
    cutoff = timezone.now() - timedelta(days=30)
    recent = Booking.objects.filter(
        member=member,
        status__in=(Booking.Status.CANCELLED_LATE, Booking.Status.NO_SHOW),
    )
    classes = recent.filter(scheduled_class__starts_at__gte=cutoff).count()
    appointments = recent.filter(appointment__starts_at__gte=cutoff).count()
    return classes + appointments >= 3
