from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        WAITLISTED = "waitlisted", "Waitlisted"
        CANCELLED = "cancelled", "Cancelled"
        CANCELLED_LATE = "cancelled_late", "Cancelled late"
        NO_SHOW = "no_show", "No-show"
        COMPLETED = "completed", "Completed"

    ACTIVE = ("confirmed", "waitlisted")

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
    # Appointment target + credit_tx land with their tickets (7q9, xts);
    # until then every booking targets a class.
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CONFIRMED
    )
    source = models.CharField(max_length=64, default="app")
    idempotency_key = models.CharField(max_length=64, unique=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.UniqueConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "member", "scheduled_class"],
                condition=models.Q(status__in=["confirmed", "waitlisted"]),
                name="one_active_class_booking",
            ),
        ]

    def clean(self):
        super().clean()
        if self.scheduled_class_id is None:
            raise ValidationError({"scheduled_class": "A booking must target a class."})

    def __str__(self):
        return f"{self.member} → {self.scheduled_class} ({self.status})"
