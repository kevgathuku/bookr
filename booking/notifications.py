"""Post-commit member notices for cancels and session cancellations.

The cancel services stay silent; the email goes out only after the
transaction commits, so members are never notified of rolled-back state.
Sending is best-effort: a mail outage must never fail the booking write.
"""

import logging
from typing import assert_never

from django.core.mail import send_mail

from booking.models import CancellationPolicy, CancellationRecord

logger = logging.getLogger(__name__)


def _send(subject, body, to):
    try:
        send_mail(subject, body, None, [to])
    except Exception:
        logger.exception("member notice failed")


def _address(member):
    if not member.email:
        raise ValueError(
            f"member {member.username} has no email; refusing to invent one",
        )
    return member.email


def notify_member_cancel(record):
    """Outcome notice for one member cancel. Reads the immutable record."""
    snap = record.snapshot
    session_label = f"{snap['offering_title']} at {snap['session_starts_at']}"
    reason = snap["reason"] or "—"
    _send(
        f"Booking cancelled: {session_label}",
        f"Your booking for {session_label} was "
        f"{_outcome_text(record)}. Reason: {reason}.",
        _address(record.member),
    )


def _outcome_text(record):
    snap = record.snapshot
    refunded = snap["credits_refunded"]
    if snap["cause"] == "staff_decision":
        return f"cancelled by staff and {refunded} credit(s) refunded"
    if not record.was_late:
        return f"cancelled free and {refunded} credit(s) refunded"
    return _late_outcome_text(record, refunded)


def _late_outcome_text(record: CancellationRecord, refunded: int) -> str:
    if record.penalty_waived:
        return (
            "cancelled late but the penalty was waived and "
            f"{refunded} credit(s) refunded"
        )
    enforcement = CancellationPolicy.Enforcement(record.enforcement_applied)
    if enforcement == CancellationPolicy.Enforcement.STRIKE:
        return f"cancelled late and {refunded} credit(s) refunded, strike recorded"
    if refunded:
        return f"cancelled late and {refunded} credit(s) refunded"
    if (
        enforcement == CancellationPolicy.Enforcement.LOSE_CREDIT
        or enforcement == CancellationPolicy.Enforcement.NONE
    ):
        return "cancelled late and the credit was forfeited"
    assert_never(enforcement)


def notify_session_cancelled(record):
    """One member's share of a provider-side session cancellation."""
    snap = record.snapshot
    session_label = f"{snap['offering_title']} at {snap['session_starts_at']}"
    reason = snap["reason"] or "—"
    _send(
        f"Class cancelled: {session_label}",
        f"{session_label} was cancelled by the studio; "
        f"{snap['credits_refunded']} credit(s) refunded. Reason: {reason}.",
        _address(record.member),
    )


def notify_promoted(booking):
    """A freed seat is now held for the longest-waiting queued member."""
    session = booking.session
    title = session.offering.title
    starts = session.starts_at.isoformat()
    hold_until = booking.hold_expires_at.isoformat()
    session_label = f"{title} at {starts}"
    _send(
        f"Seat held: {session_label}",
        f"A seat opened in {session_label} and is held for you until "
        f"{hold_until} in venue time. "
        f"{booking.credits_spent} credit(s) were debited.",
        _address(booking.member),
    )


def notify_hold_expired(booking, refunded):
    """A lapsed hold released the seat; the stamp is refunded."""
    session = booking.session
    title = session.offering.title
    starts = session.starts_at.isoformat()
    session_label = f"{title} at {starts}"
    _send(
        f"Hold lapsed: {session_label}",
        f"Your held seat in {session_label} lapsed and was released; "
        f"{refunded} credit(s) refunded.",
        _address(booking.member),
    )
