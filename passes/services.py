"""Plan-membership balance moves. Balances live on the membership row
(credits_remaining cache) with the ledger as the append-only truth.
"""

from django.db import transaction

from passes.models import CreditLedger


def spend_for_booking(membership, amount, booking):
    """Debit a plan membership for one booking; write the BOOKING ledger row.

    Zero spends nothing and writes nothing (monthly plans, comped seats).
    Runs inside the caller's transaction: CreditInsufficient rolls back the
    booking too, so nothing is ever half-written.
    """
    from booking.errors import CreditInsufficient
    from passes.models import Membership

    if amount <= 0:
        return None
    with transaction.atomic():
        locked = Membership.objects.select_for_update().get(pk=membership.pk)
        if locked.credits_remaining < amount:
            raise CreditInsufficient("No valid membership covers this booking.")
        CreditLedger.objects.create(
            membership=locked,
            booking=booking,
            delta=-amount,
            reason=CreditLedger.Reason.BOOKING,
        )
        locked.credits_remaining -= amount
        locked.save(update_fields=["credits_remaining"])
    return locked
