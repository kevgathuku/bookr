from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from passes.models import PlanType
from scheduling.catalogue import ClassCategory

ACTIVE_STATUSES = ("booked",)


class Booking(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CANCELLED = "cancelled", "Cancelled"
        LATE_CANCELLED = "late_cancelled", "Late cancelled"
        NO_SHOW = "no_show", "No-show"
        ATTENDED = "attended", "Attended"

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
    credits_spent = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.BOOKED
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["session", "member"],
                condition=models.Q(status__in=ACTIVE_STATUSES),
                name="one_active_session_booking",
            ),
        ]

    def clean(self):
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

    def __str__(self):
        return f"{self.member} → {self.session} ({self.status})"


class CancellationPolicy(models.Model):
    """Scoped cancellation rule. NULL scope fields mean "any". The most
    specific matching rule wins; priority breaks ties. No fee path."""

    class Enforcement(models.TextChoices):
        NONE = "none", "None"
        STRIKE = "strike", "Strike"
        LOSE_CREDIT = "lose_credit", "Lose credit"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="cancellation_policies",
    )
    venue = models.ForeignKey(
        "organizations.Venue", null=True, blank=True, on_delete=models.CASCADE
    )
    class_category = models.CharField(
        max_length=20, choices=ClassCategory.choices, null=True, blank=True
    )
    plan_type = models.CharField(
        max_length=20, choices=PlanType.choices, null=True, blank=True
    )
    late_cancel_hours = models.PositiveIntegerField(
        help_text="Cancel at least this many hours before start."
    )
    enforcement = models.CharField(max_length=20, choices=Enforcement.choices)
    priority = models.IntegerField(default=0)

    SCOPE_FIELDS = (  # noqa: WPS115 — scope tuple lives on the model per design
        "venue_id",
        "class_category",
        "plan_type",
    )

    @property
    def specificity(self) -> int:
        return sum(getattr(self, field) is not None for field in self.SCOPE_FIELDS)

    def overlaps(self, other: CancellationPolicy) -> bool:
        """True if some booking context could match both rules."""
        for field in self.SCOPE_FIELDS:
            mine, theirs = getattr(self, field), getattr(other, field)
            if mine is not None and theirs is not None and mine != theirs:
                return False
        return True

    def clean(self):
        # Reject ambiguous rules: equally specific, same priority,
        # overlapping scope.
        rivals = CancellationPolicy.objects.filter(
            organization_id=self.organization_id, priority=self.priority
        ).exclude(pk=self.pk)
        for rival in rivals:
            if rival.specificity == self.specificity and self.overlaps(rival):
                raise ValidationError(
                    f"Ambiguous: overlaps equally specific rule #{rival.pk}."
                )

    def __str__(self):
        return f"policy #{self.pk} ({self.specificity} scopes)"
