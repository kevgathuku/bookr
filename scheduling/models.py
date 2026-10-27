from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Func, Q

from organizations.tenancy import VenueScopedQuerySet

# Range over [starts_at, ends_at): back-to-back classes share a bound but do
# not overlap, so no buffer logic leaks into the constraint.


def _overlap_range() -> Func:
    return Func("starts_at", "ends_at", function="TSTZRANGE")


class ClassType(models.Model):
    objects = VenueScopedQuerySet.as_manager()
    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="class_types"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(default="", blank=True)
    capacity_default = models.PositiveIntegerField(null=True, blank=True)
    duration_min = models.PositiveIntegerField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "name"], name="classtype_unique_per_venue"
            ),
        ]

    def __str__(self):
        return f"{self.name} @ {self.venue}"


class Room(models.Model):
    objects = VenueScopedQuerySet.as_manager()
    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="rooms"
    )
    name = models.CharField(max_length=200)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "name"], name="room_unique_per_venue"
            ),
        ]

    def __str__(self):
        return f"{self.name} @ {self.venue}"


class ScheduledClass(models.Model):
    objects = VenueScopedQuerySet.as_manager()

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    venue = models.ForeignKey(
        "organizations.Venue",
        on_delete=models.CASCADE,
        related_name="scheduled_classes",
    )
    class_type = models.ForeignKey(
        ClassType, on_delete=models.PROTECT, related_name="scheduled_classes"
    )
    room = models.ForeignKey(
        Room, on_delete=models.PROTECT, related_name="scheduled_classes"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="taught_classes",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity_override = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SCHEDULED
    )
    checkin_opens_minutes = models.PositiveIntegerField(default=30)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="scheduled_class_ends_after_starts",
            ),
            ExclusionConstraint(
                name="no_double_booked_room",
                expressions=[
                    ("venue", RangeOperators.EQUAL),
                    ("room", RangeOperators.EQUAL),
                    (_overlap_range(), RangeOperators.OVERLAPS),
                ],
                condition=~Q(
                    status="cancelled"
                ),  # Status.CANCELLED; Meta cannot see the nested class
            ),
            ExclusionConstraint(
                name="no_double_booked_teacher",
                expressions=[
                    ("venue", RangeOperators.EQUAL),
                    ("teacher", RangeOperators.EQUAL),
                    (_overlap_range(), RangeOperators.OVERLAPS),
                ],
                condition=~Q(
                    status="cancelled"
                ),  # Status.CANCELLED; Meta cannot see the nested class
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

    def save(self, *args, **kwargs):
        if (
            self.pk is not None
            and type(self)
            .objects.filter(pk=self.pk, status=self.Status.COMPLETED)
            .exists()
        ):
            raise ValidationError("Completed classes are immutable.")
        super().save(*args, **kwargs)

    @property
    def capacity(self):
        """First non-null wins: override → room → type default."""
        if self.capacity_override is not None:
            return self.capacity_override
        if self.room_id is not None and self.room.capacity is not None:
            return self.room.capacity
        return self.class_type.capacity_default

    def __str__(self):
        day = self.starts_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.class_type} · {day} ({self.status})"


class TeacherSubstitution(models.Model):
    scheduled_class = models.ForeignKey(
        ScheduledClass, on_delete=models.CASCADE, related_name="substitutions"
    )
    old_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    new_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reason = models.CharField(max_length=255, default="", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    def delete(self, *args, **kwargs):
        # Append-only history: substitutions are never removed.
        raise ValidationError("Teacher substitutions are append-only.")

    def __str__(self):
        return f"{self.old_teacher} → {self.new_teacher} ({self.scheduled_class})"
