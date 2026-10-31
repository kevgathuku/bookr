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


class AllotmentExhausted(BookingError):
    """Partner holds no more seats in this session."""
