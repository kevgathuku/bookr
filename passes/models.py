from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PlanType(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    CREDIT_PACK = "credit_pack", "Credit pack"
    DROP_IN = "drop_in", "Drop-in"
    COMPLIMENTARY = "complimentary", "Complimentary"


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
        ]

    def delete(self, *args, **kwargs):
        # Append-only: rows are never edited or removed.
        from django.core.exceptions import ValidationError

        raise ValidationError("Ledger rows are append-only.")

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.membership}: {sign}{self.delta} ({self.reason})"


class Plan(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="plans"
    )
    name = models.CharField(max_length=200)
    plan_type = models.CharField(max_length=20, choices=PlanType.choices)
    validity_days = models.PositiveIntegerField(default=30)

    def __str__(self):
        return f"{self.name} ({self.plan_type})"


class Membership(models.Model):
    """A plan a specific user bought. The paying source for bookings."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plan_memberships",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="memberships")
    credits_remaining = models.PositiveIntegerField(default=0)
    starts_on = models.DateField()
    # Every membership has a known end: packs expire per plan validity,
    # monthlies at the billing period end. No open-ended memberships.
    ends_on = models.DateField()

    def clean(self):
        super().clean()
        if (
            self.starts_on is not None
            and self.ends_on is not None
            and self.ends_on < self.starts_on
        ):
            raise ValidationError("ends_on is before starts_on.")

    payment_ref = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.user} → {self.plan} ({self.credits_remaining} left)"
