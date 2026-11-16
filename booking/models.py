from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from passes.models import PlanTier

ACTIVE_STATUSES = ("booked", "waitlisted", "held")


class BookingStatus(models.TextChoices):
    """Booking lifecycle; use via Booking.Status. Adding one needs a
    migration: the booking_status_valid CHECK pins the allowed values."""

    BOOKED = "booked", "Booked"
    WAITLISTED = "waitlisted", "Waitlisted"
    HELD = "held", "Held"
    CANCELLED = "cancelled", "Cancelled"
    LATE_CANCELLED = "late_cancelled", "Late cancelled"
    NO_SHOW = "no_show", "No-show"
    ATTENDED = "attended", "Attended"


class Booking(models.Model):
    # Alias, not a nested definition: Meta's CHECK below needs the values,
    # and class bodies don't see their enclosing class's names.
    Status = BookingStatus  # noqa: WPS115 — public Booking.Status API

    session = models.ForeignKey(
        "scheduling.ClassSession", on_delete=models.CASCADE, related_name="bookings"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings"
    )
    # The membership that paid for THIS booking. Always set: drop-ins and
    # comps are memberships too. PROTECT so deleting a membership can never
    # silently change a booking's policy.
    membership = models.ForeignKey(
        "passes.Membership", on_delete=models.PROTECT, related_name="bookings"
    )
    # Credits actually debited at booking time; refunds return exactly this.
    # Waitlisted and held rows stamp zero: spend happens on confirm, never
    # on join and never on promotion.
    credits_spent = models.PositiveIntegerField(default=0)
    # Promotion reserves the seat until this moment; the sweep releases
    # lapsed holds. Set exactly when the status is Held; NULL otherwise.
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.BOOKED
    )
    # When the door marked attendance; the roster shows it, not the status.
    checked_in_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["session", "member"],
                condition=models.Q(status__in=ACTIVE_STATUSES),
                name="one_active_session_booking",
            ),
            models.CheckConstraint(
                condition=models.Q(hold_expires_at__isnull=True)
                | models.Q(status="held"),
                name="hold_requires_held",
            ),
            # The reverse of hold_requires_held: a held seat without an
            # expiry is never swept (the sweep filters hold_expires_at__lte)
            # and never confirmable, so it would pin the seat forever.
            models.CheckConstraint(
                condition=~models.Q(status="held")
                | models.Q(hold_expires_at__isnull=False),
                name="held_requires_hold",
            ),
            # save() runs clean() only (never full_clean, see save), so
            # choices= is never checked on write: this is the only guard.
            models.CheckConstraint(
                condition=models.Q(status__in=BookingStatus.values),
                name="booking_status_valid",
            ),
        ]

    def clean(self):
        # Cross-table coherence has no CHECK equivalent (constraints can't
        # join), so it lives here — on every save() — mirrored fail-fast in
        # services._validate_membership.
        super().clean()
        if (
            self.membership_id is not None
            and self.member_id is not None
            and self.membership.user_id != self.member_id
        ):
            raise ValidationError("Booking membership belongs to another user.")
        if self.membership_id is not None and self.session_id is not None:
            plan_org = self.membership.plan.organization_id
            venue_org = self.session.offering.venue.organization_id
            if plan_org != venue_org:
                raise ValidationError("Booking plan belongs to another organization.")

    def save(self, *args, **kwargs):
        # clean(), not full_clean(): the partial-unique race in
        # _create_booking relies on the DB raising IntegrityError so the
        # winner's row can be returned; unique validation here would turn
        # that race into ValidationError and break retry-safety.
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.member} → {self.session} ({self.status})"


class CancellationEnforcement(models.TextChoices):
    """Penalty a late cancel incurs; use via CancellationPolicy.Enforcement.
    Adding one needs a migration: policy and record CHECKs pin the values."""

    NONE = "none", "None"
    STRIKE = "strike", "Strike"
    LOSE_CREDIT = "lose_credit", "Lose credit"


class CancellationPolicy(models.Model):
    """One rule per behavioral tier. Tiers never overlap, so there is no
    specificity ranking and no baseline: the trio always covers every
    house booking. No fee path."""

    # Alias, not a nested definition: Meta's CHECK below needs the values,
    # and class bodies don't see their enclosing class's names.
    Enforcement = CancellationEnforcement  # noqa: WPS115 — public API

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="cancellation_policies",
    )
    tier = models.CharField(max_length=20, choices=PlanTier.choices)
    late_cancel_hours = models.PositiveIntegerField(
        help_text="Cancel at least this many hours before start."
    )
    enforcement = models.CharField(max_length=20, choices=Enforcement.choices)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # One rule per tier: the trio is created at org setup, so
            # exactly one row per tier exists structurally, not by
            # convention. A plain unique suffices (tier is non-nullable).
            models.UniqueConstraint(
                fields=["organization", "tier"],
                name="policy_org_tier_unique",
            ),
            # choices= is Python-only and save() never full_cleans, so a
            # bad value would reach resolution and match no penalty branch.
            models.CheckConstraint(
                condition=models.Q(enforcement__in=CancellationEnforcement.values),
                name="cancellationpolicy_enforcement_valid",
            ),
            # Blank "" is rejected: resolution compares tier equality, so
            # "" would be a rule that matches no booking — a dead rule.
            models.CheckConstraint(
                condition=models.Q(tier__in=PlanTier.values),
                name="cancellationpolicy_tier_valid",
            ),
        ]

    def __str__(self):
        return f"policy #{self.pk} ({self.tier})"


class CancellationCause(models.TextChoices):
    """Why a booking ended; use via CancellationRecord.Cause. Adding one
    needs a migration: the cancellationrecord_cause_valid CHECK pins it."""

    MEMBER_CANCEL = "member_cancel", "Member cancel"
    STAFF_DECISION = "staff_decision", "Staff decision"
    SESSION_CANCELLED = "session_cancelled", "Session cancelled"
    NO_SHOW = "no_show", "No-show"
    UNCLAIMED = "unclaimed", "Unclaimed"


class CancellationRecord(models.Model):
    """One immutable row per cancellation outcome. The snapshot pins the
    full context (session, member, plan, policy, actor, cause) so history
    stays readable after rules change. Never edited: forgiveness arrives
    as a linked ledger adjustment, never a rewrite."""

    # Alias, not a nested definition: Meta's CHECK below needs the values,
    # and class bodies don't see their enclosing class's names.
    Cause = CancellationCause  # noqa: WPS115 — public API

    booking = models.ForeignKey(
        Booking, on_delete=models.PROTECT, related_name="cancellation_records"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cancellation_records",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="cancellation_records",
    )
    cause = models.CharField(max_length=20, choices=Cause.choices)
    was_late = models.BooleanField()
    enforcement_applied = models.CharField(
        max_length=20, choices=CancellationPolicy.Enforcement.choices
    )
    penalty_waived = models.BooleanField(default=False)
    waived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    credits_refunded = models.PositiveIntegerField(default=0)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(penalty_waived=False)
                | models.Q(waived_by__isnull=False),
                name="waiver_requires_actor",
            ),
            models.CheckConstraint(
                condition=models.Q(was_late=True)
                | models.Q(enforcement_applied="none"),
                name="ontime_enforcement_none",
            ),
            # Append-only audit rows: a bad value written once can never be
            # corrected in place, so reject it at the door.
            models.CheckConstraint(
                condition=models.Q(cause__in=CancellationCause.values),
                name="cancellationrecord_cause_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    enforcement_applied__in=CancellationEnforcement.values
                ),
                name="cancellationrecord_enforcement_applied_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        # Append-only: forgiveness arrives as a linked ledger adjustment.
        if not self._state.adding:
            raise ValidationError("Cancel records are append-only.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"cancel record #{self.pk} ({self.cause})"
