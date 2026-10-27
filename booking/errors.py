"""Typed booking failures. Views map these to HTTP (SeatFull/DuplicateBooking
→ 409, CreditInsufficient → 402); the service never imports the web layer."""


class BookingError(Exception):
    """Base for all book_seat() failures."""


class SeatFull(BookingError):
    """Class is full and waitlist was not requested."""


class CreditInsufficient(BookingError):
    """Member has no spendable credit for this booking."""


class DuplicateBooking(BookingError):
    """Member already holds an active booking for this class."""


class TeacherUnavailable(BookingError):
    """Teacher holds an overlapping appointment (maps to 409)."""
