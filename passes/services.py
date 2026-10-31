"""Pass wallet. Balance is always SUM(delta); the used counter is a cache
updated in the same transaction, never edited directly."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from passes.models import CreditLedger, MemberPass


def issue_pass(member, product, valid_from=None):
    """Create the pass + purchase row (unlimited writes no row: delta != 0)."""
    valid_from = valid_from or timezone.now()
    member_pass = MemberPass.objects.create(
        member=member,
        product=product,
        credits_total=product.credits_total,
        valid_from=valid_from,
        valid_until=valid_from + timedelta(days=product.validity_days),
    )
    if product.credits_total:
        CreditLedger.objects.create(
            member_pass=member_pass,
            delta=product.credits_total,
            reason=CreditLedger.Reason.PURCHASE,
        )
    return member_pass


def adjust_credit(member_pass, delta, reason, staff):
    """Staff correction. Reason required; delta != 0 enforced at the DB."""
    if not reason:
        raise ValidationError({"reason": "Adjustments need a reason."})
    with transaction.atomic():
        member_pass = MemberPass.objects.select_for_update().get(pk=member_pass.pk)
        CreditLedger.objects.create(
            member_pass=member_pass,
            delta=delta,
            reason=CreditLedger.Reason.ADJUSTMENT,
            note=reason,
            created_by=staff,
        )
        member_pass.credits_used = max(
            0, member_pass.credits_total - member_pass.ledger_balance()
        )
        member_pass.save(update_fields=["credits_used"])
    return member_pass


def expire_passes(now=None):
    """Zero remaining balances on lapsed passes. Beat schedules this nightly
    once the Celery app lands (anm ticket); the function is complete alone."""
    now = now or timezone.now()
    expired = 0
    for member_pass in MemberPass.objects.filter(
        status=MemberPass.Status.ACTIVE, valid_until__lt=now
    ):
        with transaction.atomic():
            locked = MemberPass.objects.select_for_update().get(pk=member_pass.pk)
            remaining = locked.ledger_balance()
            if remaining:
                CreditLedger.objects.create(
                    member_pass=locked,
                    delta=-remaining,
                    reason=CreditLedger.Reason.EXPIRY,
                )
            locked.status = MemberPass.Status.EXPIRED
            locked.save(update_fields=["status"])
            expired += 1
    return expired


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
