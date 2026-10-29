"""One interface for every booking ending.

Callers decide the outcome (member cancel, late cancel, no-show, lapsed
hold, partner cancel); close_booking owns the mechanics every ending
shares: lock, transition, settle credit, save, notify, promote.
"""

from collections.abc import Callable
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking import notify
from booking.models import Booking
from passes.services import refund_credit, spend_credit


class _Spec(NamedTuple):
    status: str
    refund: bool
    clear_hold: bool
    notice: Callable[[Booking], None] | None


# outcome -> transition spec. Tuple, not dict: module constants stay immutable.
_OUTCOMES = (
    ("cancel", _Spec(Booking.Status.CANCELLED, True, False, notify.booking_cancelled)),
    (
        "late_cancel",
        _Spec(Booking.Status.CANCELLED_LATE, False, False, notify.booking_late_cancel),
    ),
    ("no_show", _Spec(Booking.Status.NO_SHOW, False, False, None)),
    (
        "hold_lapsed",
        _Spec(Booking.Status.CANCELLED, True, True, notify.booking_cancelled),
    ),
    ("partner_cancel", _Spec(Booking.Status.CANCELLED, False, False, None)),
    (
        "partner_late_cancel",
        _Spec(Booking.Status.CANCELLED_LATE, False, False, None),
    ),
)


def _spec_for(outcome):
    for name, spec in _OUTCOMES:
        if name == outcome:
            return spec
    raise ValidationError(f"Unknown booking outcome: {outcome}.")


def _ensure_open(locked, outcome):
    if locked.status not in (Booking.Status.CONFIRMED, Booking.Status.WAITLISTED):
        raise ValidationError("Booking is already closed.")
    if outcome == "hold_lapsed" and (
        locked.hold_until is None or locked.hold_until >= timezone.now()
    ):
        raise ValidationError("Hold has not lapsed.")


def spend_for_confirmation(booking):
    """Spend member credit for a booking turning CONFIRMED; attaches the row."""
    ledger = spend_credit(booking.member, booking)
    booking.credit_tx = ledger
    booking.save(update_fields=["credit_tx"])
    return ledger


def close_booking(booking, outcome, *, reason=""):
    """Lock, transition to the outcome status, settle credit, notify, promote.

    Raises ValidationError when the booking is already closed (sweep callers
    treat that as a race won elsewhere and move on).
    """
    spec = _spec_for(outcome)
    with transaction.atomic():
        locked = (
            Booking.objects.select_for_update(of=("self",))
            .select_related("scheduled_class", "appointment", "member")
            .get(pk=booking.pk)
        )
        _ensure_open(locked, outcome)
        freed = locked.status == Booking.Status.CONFIRMED
        if spec.refund:
            refund_credit(locked, note=reason)
        locked.status = spec.status
        fields = ["status"]
        if spec.clear_hold:
            locked.hold_until = None
            fields.append("hold_until")
        locked.save(update_fields=fields)
        if spec.notice is not None:
            spec.notice(locked)
        if freed and locked.scheduled_class_id is not None:
            from booking.tasks import promote_waitlist

            promote_waitlist.delay(class_id=locked.scheduled_class_id)
    return locked
