"""HTTP mapping for booking failures (service errors live in errors.py)."""

import contextlib

from rest_framework.exceptions import APIException

from booking.errors import BookingError, CreditInsufficient


class Conflict(APIException):
    status_code = 409
    default_detail = "Booking conflict."
    default_code = "conflict"


class PaymentRequired(APIException):
    status_code = 402
    default_detail = "Insufficient credits."
    default_code = "payment_required"


@contextlib.contextmanager
def mapped_errors():
    """Raise service errors as their HTTP equivalents.

    State conflicts (full, duplicate, closed, started) are 409; only
    the empty wallet is 402.
    """
    try:
        yield
    except CreditInsufficient as error:
        raise PaymentRequired(str(error))
    except BookingError as error:
        raise Conflict(str(error))
