from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from organizations.tenancy import VenueScopedQuerySet
from scheduling.models import ScheduledClass, _overlap_range


class Resource(models.Model):
    class Kind(models.TextChoices):
        ROOM = "room", "Room"
        EQUIPMENT = "equipment", "Equipment"
        TEACHER = "teacher", "Teacher"

    objects = VenueScopedQuerySet.as_manager()
    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="resources"
    )
    type = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=200)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "name"], name="resource_unique_per_venue"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.type}) @ {self.venue}"


class AvailabilityRule(models.Model):
    resource = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="rules"
    )
    weekday = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(weekday__lte=6), name="rule_weekday_0_to_6"
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="rule_ends_after_starts",
            ),
        ]

    def clean(self):
        super().clean()
        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "Must be after start_time."})

    def __str__(self):
        day = f"wd{self.weekday} {self.start_time}-{self.end_time}"
        return f"{self.resource} · {day}"


class AvailabilityException(models.Model):
    resource = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="exceptions"
    )
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    closed = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["resource", "date"], name="exception_once_per_day"
            ),
        ]

    def __str__(self):
        state = "closed" if self.closed else "partial"
        return f"{self.resource} · {self.date} ({state})"


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    objects = VenueScopedQuerySet.as_manager()
    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="appointments"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appointments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="given_appointments",
    )
    resource = models.ForeignKey(
        Resource,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="appointments",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SCHEDULED
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="appointment_ends_after_starts",
            ),
            ExclusionConstraint(
                name="no_double_booked_appt_teacher",
                expressions=[
                    ("venue", RangeOperators.EQUAL),
                    ("teacher", RangeOperators.EQUAL),
                    (_overlap_range(), RangeOperators.OVERLAPS),
                ],
                condition=~Q(status="cancelled"),  # Status.CANCELLED; Meta is blind
            ),
            ExclusionConstraint(
                name="no_double_booked_appt_resource",
                expressions=[
                    ("venue", RangeOperators.EQUAL),
                    ("resource", RangeOperators.EQUAL),
                    (_overlap_range(), RangeOperators.OVERLAPS),
                ],
                condition=~Q(status="cancelled"),  # Status.CANCELLED; Meta is blind
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.starts_at is not None
            and self.ends_at is not None
            and self.ends_at <= self.starts_at
        ):
            raise ValidationError({"ends_at": "Must be after starts_at."})
        # Cross-table clash: exclusion constraints cannot span tables, so
        # Python guards appointment-vs-class here (book_seat guards the
        # reverse direction for class bookings).
        clash = (
            self.teacher_id is not None
            and ScheduledClass.objects.filter(
                venue=self.venue,
                teacher=self.teacher,
                status__in=[
                    ScheduledClass.Status.SCHEDULED,
                    ScheduledClass.Status.COMPLETED,
                ],
                starts_at__lt=self.ends_at,
                ends_at__gt=self.starts_at,
            ).exists()
        )
        if clash:
            raise ValidationError("Teacher holds an overlapping class.")

    def late_cancel_cutoff(self):
        """Cancel inside [cutoff, start) counts as late (24h default)."""
        hours = self.venue.current_policy.appointment_late_cancel_hours
        return self.starts_at - timezone.timedelta(hours=hours)

    def __str__(self):
        day = self.starts_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.member} with {self.teacher} · {day}"
