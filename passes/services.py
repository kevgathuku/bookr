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


def grant_goodwill(
    *,
    organization,
    user,
    credits,
    duration_days=30,
    note="",
    created_by=None,
    incident_key,
    name=None,
):
    """Mint one goodwill grant: plan + membership + PURCHASE, atomically.

    One Membership per grant (never top up): the plan row is the grant's
    terms sheet, the incident lives in payment_ref, and the same key
    twice returns the existing membership instead of double-granting.
    """
    from datetime import timedelta

    from django.db import IntegrityError
    from django.utils import timezone

    from passes.models import Entitlement, Membership, Plan, PlanType, Validity

    if credits <= 0:
        raise ValidationError("Goodwill grants move a positive credit count.")
    with transaction.atomic():
        existing = Membership.objects.filter(
            user=user, payment_ref=incident_key
        ).first()
        if existing is not None:
            return existing, False
        plan, _ = Plan.objects.get_or_create(
            organization=organization,
            name=name or f"Goodwill — {incident_key}",
            defaults={
                "plan_type": PlanType.COMPLIMENTARY,
                "entitlement": Entitlement.CREDITS,
                "credits_included": credits,
                "validity": Validity.FIXED_DURATION,
                "duration_days": duration_days,
            },
        )
        try:
            membership = Membership.objects.create(
                user=user,
                plan=plan,
                credits_remaining=credits,
                starts_on=timezone.now().date(),
                valid_until=timezone.now().date() + timedelta(days=duration_days),
                payment_ref=incident_key,
            )
        except IntegrityError:
            # Lost a same-incident race: the winner's membership is the answer.
            return (
                Membership.objects.get(user=user, payment_ref=incident_key),
                False,
            )
        post_entry(
            membership,
            credits,
            CreditLedger.Reason.PURCHASE,
            note=note,
            created_by=created_by,
        )
        return membership, True
