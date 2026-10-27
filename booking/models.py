from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

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
