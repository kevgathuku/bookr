"""HTTP mapping for booking failures (service errors live in errors.py)."""

from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = 409
    default_detail = "Booking conflict."
    default_code = "conflict"


class PaymentRequired(APIException):
    status_code = 402
    default_detail = "Insufficient credits."
    default_code = "payment_required"
