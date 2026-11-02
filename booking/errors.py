"""Typed booking failures. Views map them to HTTP (SeatFull/DuplicateBooking
→ 409, CreditInsufficient → 402); the service never imports the web layer."""


class BookingError(Exception):
    """Base for all book_session() failures."""


class SeatFull(BookingError):
    """Session is full."""


class CreditInsufficient(BookingError):
    """Member has no valid membership covering this booking."""


class DuplicateBooking(BookingError):
    """Member already holds an active booking for this session."""


class NotHeld(BookingError):
    """Booking holds no confirmable seat: not held, or hold expired."""


class AllotmentExhausted(BookingError):
    """Partner holds no more seats in this session."""


class AlreadyCancelled(BookingError):
    """Booking is no longer active; repeats change nothing."""


class SessionStarted(BookingError):
    """Session has started or been provider-cancelled."""


class InvalidWaiver(BookingError):
    """Waiver asked for something unwaivable: no penalty to waive, nothing
    forfeited, or forgiveness that must happen inline at cancel time."""
