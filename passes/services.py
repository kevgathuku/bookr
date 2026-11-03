"""Plan-membership balance moves. Balances live on the membership row
(credits_remaining cache) with the ledger as the append-only truth.
Every movement goes through post_entry(); nothing edits the cache
directly.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from booking.errors import CreditInsufficient
from passes.models import CreditLedger


def post_entry(
    membership,
    delta,
    reason,
    booking=None,
    note="",
    created_by=None,
    cancellation_record=None,
):
    """Write one ledger row and bump the cached balance, atomically.

    The single choke-point for every credit movement: zero deltas are
    refused (the ledger forbids them), unlimited memberships take no
    rows at all, and the floor is enforced under the row lock so
    concurrent spenders cannot drive the balance negative.
    """
    from passes.models import Membership

    if delta == 0:
        raise ValidationError("Ledger rows must move credits.")
    with transaction.atomic():
        locked = Membership.objects.select_for_update().get(pk=membership.pk)
        if locked.credits_remaining is None:
            raise ValidationError("Unlimited memberships take no ledger rows.")
        balance = locked.credits_remaining + delta
        if balance < 0:
            raise CreditInsufficient("No valid membership covers this booking.")
        row = CreditLedger.objects.create(
            membership=locked,
            booking=booking,
            delta=delta,
            reason=reason,
            note=note,
            created_by=created_by,
            cancellation_record=cancellation_record,
        )
        locked.credits_remaining = balance
        locked.save(update_fields=["credits_remaining"])
    return row


def spend_for_booking(membership, amount, booking):
    """Debit a plan membership for one booking; write the BOOKING ledger row.

    Zero spends nothing and writes nothing (unlimited plans, comped seats).
    Runs inside the caller's transaction: CreditInsufficient rolls back the
    booking too, so nothing is ever half-written.
    """
    if amount <= 0:
        return None
    return post_entry(
        membership,
        -amount,
        CreditLedger.Reason.BOOKING,
        booking=booking,
    )
