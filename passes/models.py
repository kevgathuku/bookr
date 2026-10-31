from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from organizations.tenancy import VenueScopedQuerySet


class PlanType(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    CREDIT_PACK = "credit_pack", "Credit pack"
    DROP_IN = "drop_in", "Drop-in"
    COMPLIMENTARY = "complimentary", "Complimentary"


class PassProduct(models.Model):
    objects = VenueScopedQuerySet.as_manager()

    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="pass_products"
    )
    name = models.CharField(max_length=200)
    credits_total = models.PositiveIntegerField(null=True, blank=True)
    validity_days = models.PositiveIntegerField()
    applicable_class_types = models.ManyToManyField(
        "scheduling.ClassType", blank=True, related_name="pass_products"
    )
    transferable = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "name"], name="passproduct_unique_per_venue"
            ),
        ]

    def __str__(self):
        return f"{self.name} @ {self.venue}"


class MemberPass(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        DEPLETED = "depleted", "Depleted"

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passes"
    )
    product = models.ForeignKey(
        PassProduct, on_delete=models.PROTECT, related_name="issued"
    )
    credits_total = models.PositiveIntegerField(null=True, blank=True)
    credits_used = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )

    @property
    def is_unlimited(self):
        return self.credits_total is None

    def ledger_balance(self):
        from django.db.models import Sum

        return self.entries.aggregate(total=Sum("delta"))["total"] or 0

    def covers(self, class_type, now):
        """Valid, live, and applicable to this class type."""
        if self.status != self.Status.ACTIVE:
            return False
        if not (self.valid_from <= now <= self.valid_until):
            return False
        if not self.is_unlimited and self.credits_used >= self.credits_total:
            return False
        applicable = self.product.applicable_class_types
        return not applicable.exists() or applicable.filter(pk=class_type.pk).exists()

    def __str__(self):
        return f"{self.product} → {self.member} ({self.status})"


class CreditLedger(models.Model):
    class Reason(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        BOOKING = "booking", "Booking"
        REFUND = "refund", "Refund"
        FORFEIT = "forfeit", "Forfeit"
        EXPIRY = "expiry", "Expiry"
        ADJUSTMENT = "adjustment", "Adjustment"

    # `pass` is reserved: the FK is member_pass, never edited, only appended.
    # Nullable in the expand phase: new rows key off membership instead.
    # Contract removes member_pass and enforces membership.
    member_pass = models.ForeignKey(
        MemberPass,
        on_delete=models.PROTECT,
        related_name="entries",
        null=True,
        blank=True,
    )
    membership = models.ForeignKey(
        "Membership",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
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
        ]

    def delete(self, *args, **kwargs):
        # Append-only: rows are never edited or removed.
        from django.core.exceptions import ValidationError

        raise ValidationError("Ledger rows are append-only.")

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        holder = self.membership if self.membership_id else self.member_pass
        return f"{holder}: {sign}{self.delta} ({self.reason})"


class MembershipPlan(models.Model):
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
    plan = models.ForeignKey(
        MembershipPlan, on_delete=models.PROTECT, related_name="memberships"
    )
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
