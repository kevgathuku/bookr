"""Member notices: cancelled, promoted, late-cancel. Console backend in
dev/test (assert via mail.outbox); SMTP in prod through EMAIL_URL."""

from django.core.mail import send_mail

FALLBACK_DOMAIN = "example.com"


def _address(member):
    if member.email:
        return member.email
    username = member.username
    return "@".join((username, FALLBACK_DOMAIN))  # noqa: FLY002 — f-string trips WPS237


def _target_label(booking):
    if booking.scheduled_class_id is not None:
        klass = booking.scheduled_class
        day = klass.starts_at.strftime("%Y-%m-%d %H:%M")
        name = klass.class_type.name
        return f"{name} at {day}"
    return f"appointment {booking.appointment_id}"


def booking_cancelled(booking):
    member = booking.member
    send_mail(
        "Booking cancelled",
        f"Your booking for {_target_label(booking)} is cancelled; "
        "the credit is back on your pass.",
        None,
        [_address(member)],
    )


def booking_promoted(booking):
    member = booking.member
    send_mail(
        "You're off the waitlist",
        f"A seat opened for {_target_label(booking)} and it is yours. See you there.",
        None,
        [_address(member)],
    )


def booking_late_cancel(booking):
    member = booking.member
    send_mail(
        "Late cancellation",
        f"Cancelling {_target_label(booking)} inside the cutoff window "
        "forfeits the credit.",
        None,
        [_address(member)],
    )
