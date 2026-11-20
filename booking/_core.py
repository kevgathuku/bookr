"""Shared booking kernel: optimistic loads, guarded writes, post-commit notices.

Seat allocation (services) and outcomes (cancellations) mutate the same
Booking rows; the lock shapes and the notify-after-commit rule live here
once so the two modules cannot drift apart. Cancel- and book-specific
logic stays where it is — this module owns transitions, not decisions.
"""

import dataclasses
from datetime import datetime

from django.db import transaction
from django.db.models import F

from booking.errors import AlreadyCancelled, ConcurrentWrite, SessionStarted
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


def get_session(session_id: SessionId) -> ClassSession:
    """Load one session with its offering and venue attached.

    Occupancy reads from this snapshot are provisional: seat-taking units
    validate them with bump_session before any seat moves."""
    return ClassSession.objects.select_related("offering", "offering__venue").get(
        pk=session_id
    )


def bump_session(session: ClassSession) -> ClassSession:
    """Claim the session snapshot: exactly one taker wins per version.

    Seat-taking validates the occupancy count read from `session` by
    bumping its version conditionally. Zero rows means another writer
    (a booking, a promotion, a session cancel) moved the row first, so
    the unit re-reads and decides again."""
    updated = ClassSession.objects.filter(
        pk=session.pk, version=session.version
    ).update(version=F("version") + 1)
    if not updated:
        raise ConcurrentWrite("Session changed under a concurrent writer.")
    session.version += 1
    return session


def load_open_booking(
    booking_id: BookingId, moment: datetime, allow_started: bool = False
) -> LoadedBooking:
    """Load one booking with its session, plan, and member attached.

    Raises when the booking is no longer active, its session is
    cancelled, or it already started (unless observed absence is the
    point). Callers assert narrower status themselves.
    """
    # No row lock: writers after this point go through transition_booking,
    # whose conditional UPDATE (pk + version) rejects stale writes on any
    # backend. The checks below still run on the loaded state; a concurrent
    # transition after the load surfaces as AlreadyCancelled at write time.
    booking = Booking.objects.select_related(
        "session__offering__venue__organization",
        "membership__plan",
        "member",
    ).get(pk=booking_id)
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


def transition_booking(booking: Booking, **fields) -> Booking:
    """Write booking fields exactly once: the UPDATE only applies when no
    concurrent writer moved the row since this instance was loaded. The
    version bump is server-side (F), so read-modify-write cannot interleave
    on any backend, including SQLite."""
    updated = Booking.objects.filter(pk=booking.pk, version=booking.version).update(
        version=F("version") + 1, **fields
    )
    if not updated:
        raise AlreadyCancelled("Booking changed under a concurrent writer.")
    booking.version += 1
    for name, value in fields.items():
        setattr(booking, name, value)
    return booking


def committed(record, notify):
    """Register a post-commit notice; the write itself already happened."""
    transaction.on_commit(lambda: notify(record))
    return record
