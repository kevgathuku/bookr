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


def _spend_from(member_pass, booking):
    CreditLedger.objects.create(
        member_pass=member_pass,
        booking=booking,
        delta=-1,
        reason=CreditLedger.Reason.BOOKING,
    )
    member_pass.credits_used += 1
    if member_pass.credits_used >= member_pass.credits_total:
        member_pass.status = MemberPass.Status.DEPLETED
    member_pass.save(update_fields=["credits_used", "status"])
    return member_pass.entries.latest("created_at")


def _first_valid(candidates, class_type, now, unlimited_only):
    for member_pass in candidates:
        if member_pass.is_unlimited is unlimited_only and member_pass.covers(
            class_type, now
        ):
            return member_pass
    return None


def spend_credit(member, booking):
    """Oldest-valid-first, unlimited before limited. Must run inside the
    booking transaction (row locks serialize the last-credit race). Returns
    the ledger row, or None for unlimited (nothing to deplete)."""
    from booking.errors import CreditInsufficient

    now = timezone.now()
    class_type = booking.scheduled_class.class_type
    candidates = (
        MemberPass.objects.select_for_update()
        .filter(
            member=member,
            status=MemberPass.Status.ACTIVE,
            valid_from__lte=now,
            valid_until__gte=now,
        )
        .select_related("product")
        .order_by("valid_from")
    )
    if _first_valid(candidates, class_type, now, True) is not None:
        return None
    limited = _first_valid(candidates, class_type, now, False)
    if limited is None:
        raise CreditInsufficient("No valid pass covers this class.")
    return _spend_from(limited, booking)


def refund_credit(booking):
    """Return the spent credit; unlimited bookings spent nothing."""
    if booking.credit_tx is None:
        return None
    with transaction.atomic():
        member_pass = MemberPass.objects.select_for_update().get(
            pk=booking.credit_tx.member_pass_id
        )
        CreditLedger.objects.create(
            member_pass=member_pass,
            booking=booking,
            delta=1,
            reason=CreditLedger.Reason.REFUND,
        )
        member_pass.credits_used = max(0, member_pass.credits_used - 1)
        if member_pass.status == MemberPass.Status.DEPLETED:
            member_pass.status = MemberPass.Status.ACTIVE
        member_pass.save(update_fields=["credits_used", "status"])
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
