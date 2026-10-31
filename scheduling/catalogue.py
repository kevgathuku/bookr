from django.conf import settings
from django.db import models


class ClassCategory(models.TextChoices):
    GROUP = "group", "Group"
    PRIVATE = "private", "Private"
    WORKSHOP = "workshop", "Workshop"


class ClassOffering(models.Model):
    """The "what": venue, teacher, title, category, duration, and per-seat
    credit price. All immutable per session and per booking."""

    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="offerings"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="taught_offerings",
    )
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=ClassCategory.choices)
    duration_minutes = models.PositiveIntegerField(default=60)
    credit_cost = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.title} ({self.category})"


class ClassSession(models.Model):
    """The "when": one occurrence of an offering. End derives from start
    plus the offering duration — never stored, so the two cannot disagree."""

    offering = models.ForeignKey(
        ClassOffering, on_delete=models.CASCADE, related_name="sessions"
    )
    starts_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=15)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    @property
    def ends_at(self):
        from datetime import timedelta

        return self.starts_at + timedelta(minutes=self.offering.duration_minutes)

    def __str__(self):
        title = self.offering.title
        day = self.starts_at.strftime("%Y-%m-%d %H:%M")
        return f"{title} · {day}"
