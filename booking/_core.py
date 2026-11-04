"""Shared booking kernel: row locks, locked loads, post-commit notices.

Seat allocation (services) and outcomes (cancellations) mutate the same
Booking rows; the lock shapes and the notify-after-commit rule live here
once so the two modules cannot drift apart. Cancel- and book-specific
logic stays where it is — this module owns transitions, not decisions.
"""

import dataclasses
from datetime import datetime

from django.db import transaction

from booking.errors import AlreadyCancelled, SessionStarted
from booking.models import Booking
from common.ids import BookingId, SessionId
from organizations.models import Venue
from scheduling.models import ClassSession


@dataclasses.dataclass(frozen=True)
class LoadedBooking:
    """One locked booking with its session and venue. The organization
    always comes from the venue link, never a second field."""

    booking: Booking
    session: ClassSession
    venue: Venue


def lock_session(session_id: SessionId) -> ClassSession:
    """Row-lock one session with its offering and venue attached.

    The occupancy gate: _is_full's count is only meaningful inside this lock."""
    return (
        ClassSession.objects.select_for_update()
        .select_related("offering", "offering__venue")
        .get(pk=session_id)
    )


def load_open_booking(
    booking_id: BookingId, moment: datetime, allow_started: bool = False
) -> LoadedBooking:
    """Row-lock one booking with its session, plan, and member attached.

    Raises when the booking is no longer active, its session is
    cancelled, or it already started (unless observed absence is the
    point). Callers assert narrower status themselves.
    """
    booking = (
        Booking.objects.select_for_update()
        .select_related(
            "session__offering__venue__organization",
            "membership__plan",
            "member",
        )
        .get(pk=booking_id)
    )
    session = booking.session
    if booking.status not in (Booking.Status.BOOKED, Booking.Status.HELD):
        raise AlreadyCancelled("Booking is no longer active.")
    if session.cancelled_at is not None:
        raise SessionStarted("Session has been cancelled.")
    started = session.starts_at <= moment
    if started and not allow_started:
        raise SessionStarted(
            "Session has already started; record attendance with no-show."
        )
    return LoadedBooking(
        booking=booking,
        session=session,
        venue=session.offering.venue,
    )


def committed(record, notify):
    """Register a post-commit notice; the write itself already happened."""
    transaction.on_commit(lambda: notify(record))
    return record
