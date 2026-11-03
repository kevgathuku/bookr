from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PlanType(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    CREDIT_PACK = "credit_pack", "Credit pack"
    DROP_IN = "drop_in", "Drop-in"
    # House-granted: goodwill compensation, staff comps. Never the partner
    # vehicle — that is AGGREGATOR below.
    COMPLIMENTARY = "complimentary", "Complimentary"
    # The aggregator partner vehicle only, created solely by
    # _partner_membership. Carries no money and no ledger rows.
    AGGREGATOR = "aggregator", "Aggregator"
    # Employment benefit (compensation cost), never a sale: free classes
    # for staff. Distinct from COMPLIMENTARY so finance and future
    # plan_type-scoped policies never confuse the two.
    STAFF = "staff", "Staff"


class Entitlement(models.TextChoices):
    UNLIMITED = "unlimited", "Unlimited"
    CREDITS = "credits", "Credits"


class Validity(models.TextChoices):
    OPEN_ENDED = "open_ended", "Open-ended"
    FIXED_DURATION = "fixed_duration", "Fixed duration"
    # Manual re-purchase per period; no billing machinery (SPEC non-goal).
    RECURRING = "recurring", "Recurring"


class CreditLedger(models.Model):
    class Reason(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        BOOKING = "booking", "Booking"
        REFUND = "refund", "Refund"
        FORFEIT = "forfeit", "Forfeit"
        EXPIRY = "expiry", "Expiry"
        ADJUSTMENT = "adjustment", "Adjustment"

    membership = models.ForeignKey(
        "Membership",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    booking = models.ForeignKey(
        "booking.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    delta = models.IntegerField()
    reason = models.CharField(max_length=16, choices=Reason.choices)
    note = models.CharField(max_length=280, blank=True, default="")
    # Retroactive waiver marker: the compensating ADJUSTMENT for one
    # forfeited cancel. One row per record (unique); the record itself is
    # never edited. Strike waivers are inline-only — strikes move no
    # money, so there is nothing to compensate (see waive_record).
    cancellation_record = models.ForeignKey(
        "booking.CancellationRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waiver_adjustments",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(delta=0),
                name="ledger_delta_nonzero",
            ),
            models.UniqueConstraint(
                fields=["cancellation_record"],
                name="one_waiver_per_record",
            ),
            models.UniqueConstraint(
                fields=["booking", "reason"],
                condition=models.Q(booking__isnull=False),
                name="one_spend_and_refund_per_booking",
            ),
        ]

    def delete(self, *args, **kwargs):
        # Append-only: rows are never edited or removed.
        from django.core.exceptions import ValidationError

        raise ValidationError("Ledger rows are append-only.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Ledger rows are append-only.")
        return super().save(*args, **kwargs)

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.membership}: {sign}{self.delta} ({self.reason})"


class Plan(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="plans"
    )
    name = models.CharField(max_length=200)
    # Product label only: charge and window behavior come from
    # entitlement/validity below, never from this field.
    plan_type = models.CharField(max_length=20, choices=PlanType.choices)
    entitlement = models.CharField(max_length=10, choices=Entitlement.choices)
    credits_included = models.PositiveIntegerField(null=True, blank=True)
    validity = models.CharField(max_length=20, choices=Validity.choices)
    duration_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(
                    entitlement=Entitlement.UNLIMITED,
                    credits_included__isnull=True,
                )
                | models.Q(
                    entitlement=Entitlement.CREDITS,
                    credits_included__isnull=False,
                    credits_included__gt=0,
                ),
                name="plan_credits_match_entitlement",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    validity=Validity.OPEN_ENDED,
                    duration_days__isnull=True,
                )
                | models.Q(
                    validity__in=[
                        Validity.FIXED_DURATION,
                        Validity.RECURRING,
                    ],
                    duration_days__isnull=False,
                    duration_days__gt=0,
                ),
                name="plan_duration_match_validity",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        errors.update(self._entitlement_errors())
        errors.update(self._validity_errors())
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.name} ({self.plan_type})"

    def _entitlement_errors(self):
        if self.entitlement == Entitlement.UNLIMITED:
            if self.credits_included is not None:
                return {"credits_included": "Unlimited plans carry no credit count."}
            return {}
        if self.credits_included is None or self.credits_included <= 0:
            return {"credits_included": "Credit plans need a positive count."}
        return {}

    def _validity_errors(self):
        if self.validity == Validity.OPEN_ENDED:
            if self.duration_days is not None:
                return {"duration_days": "Open-ended plans carry no duration."}
            return {}
        if self.duration_days is None or self.duration_days <= 0:
            return {"duration_days": "Fixed and recurring plans need a duration."}
        return {}


class Membership(models.Model):
    """A plan a specific user bought. The paying source for bookings."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plan_memberships",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="memberships")
    # NULL = unlimited (no balance to track); credit memberships hold a count.
    credits_remaining = models.PositiveIntegerField(null=True, blank=True, default=0)
    starts_on = models.DateField()
    # NULL = never expires (open-ended plans, the partner vehicle).
    # Fixed/recurring memberships always carry a known end.
    valid_until = models.DateField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True)
                | models.Q(valid_until__gte=models.F("starts_on")),
                name="membership_dates_ordered",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.starts_on is not None
            and self.valid_until is not None
            and self.valid_until < self.starts_on
        ):
            raise ValidationError("valid_until is before starts_on.")

    payment_ref = models.CharField(max_length=100, blank=True)

    def __str__(self):
        if self.credits_remaining is None:
            return f"{self.user} → {self.plan} (unlimited)"
        return f"{self.user} → {self.plan} ({self.credits_remaining} left)"
