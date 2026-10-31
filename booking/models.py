from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from passes.models import PlanType
from scheduling.catalogue import ClassCategory

ACTIVE_STATUSES = ("confirmed", "waitlisted")


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        WAITLISTED = "waitlisted", "Waitlisted"
        CANCELLED = "cancelled", "Cancelled"
        CANCELLED_LATE = "cancelled_late", "Cancelled late"
        NO_SHOW = "no_show", "No-show"
        COMPLETED = "completed", "Completed"

    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="bookings"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings"
    )
    scheduled_class = models.ForeignKey(
        "scheduling.ScheduledClass",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bookings",
    )
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bookings",
    )
    # Appointment target lands with its ticket (7q9); until then every
    # booking targets a class.
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CONFIRMED
    )
    source = models.CharField(max_length=64, default="app")
    idempotency_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    hold_until = models.DateTimeField(null=True, blank=True)
    credit_tx = models.ForeignKey(
        "passes.CreditLedger",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="settled_bookings",
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "member", "scheduled_class"],
                condition=models.Q(status__in=ACTIVE_STATUSES),
                name="one_active_class_booking",
            ),
            models.UniqueConstraint(
                fields=["venue", "member", "appointment"],
                condition=models.Q(status__in=ACTIVE_STATUSES),
                name="one_active_appointment_booking",
            ),
        ]

    def clean(self):
        super().clean()
        targets = [self.scheduled_class_id, self.appointment_id]
        if sum(target is not None for target in targets) != 1:
            raise ValidationError(
                "A booking targets exactly one of class, appointment."
            )

    def __str__(self):
        return f"{self.member} → {self.scheduled_class} ({self.status})"


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
