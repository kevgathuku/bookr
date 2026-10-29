"""Member/staff endings: outcome determination. The lock → transition →
settle → notify → promote mechanics live in endings.close_booking."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking.endings import close_booking
from booking.models import Booking


def _window_hours(booking):
    policy = booking.venue.policy_for(booking.member)
    if booking.scheduled_class_id is not None:
        return policy.class_late_cancel_hours
    return policy.appointment_late_cancel_hours


def _target(booking):
    return booking.scheduled_class or booking.appointment


def cancel_booking(actor, booking, *, staff_override=False, reason=""):
    """Pick the cancel outcome under window rules; close_booking does the rest."""
    current = Booking.objects.select_related("scheduled_class", "appointment").get(
        pk=booking.pk
    )
    if staff_override:
        return close_booking(current, "cancel", reason=reason)
    target = _target(current)
    cutoff = target.starts_at - timedelta(hours=_window_hours(current))
    outcome = "cancel" if timezone.now() <= cutoff else "late_cancel"
    return close_booking(current, outcome)


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
    current = Booking.objects.select_related("scheduled_class", "appointment").get(
        pk=booking.pk
    )
    if current.status != Booking.Status.CONFIRMED:
        raise ValidationError("Only confirmed bookings can no-show.")
    target = _target(current)
    now = timezone.now()
    if not target.ends_at <= now <= target.ends_at + timedelta(hours=2):
        raise ValidationError("No-show window is 2h after the end.")
    return close_booking(current, "no_show")


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
