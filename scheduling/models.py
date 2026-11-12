from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import DateTimeField, F


class SessionEndsAt(models.Func):
    """Session end = starts_at + offering duration, on any backend.

    Django compiles duration multiplication on Postgres but not sqlite
    (its guard allowlists exact field types; duration_minutes is a
    PositiveIntegerField), so each backend renders natively.
    """

    output_field = DateTimeField()
    arity = 2

    def as_postgresql(self, compiler, connection):
        lhs, lhs_params = compiler.compile(self.source_expressions[0])
        rhs, rhs_params = compiler.compile(self.source_expressions[1])
        return (
            f"({lhs} + ({rhs} || ' minutes')::interval)",
            (*lhs_params, *rhs_params),
        )

    def as_sqlite(self, compiler, connection):
        lhs, lhs_params = compiler.compile(self.source_expressions[0])
        rhs, rhs_params = compiler.compile(self.source_expressions[1])
        return (
            f"(datetime({lhs}, '+' || {rhs} || ' minutes'))",
            (*lhs_params, *rhs_params),
        )


def derived_end():
    """DB expression matching ClassSession.ends_at (start + duration)."""
    return SessionEndsAt(F("starts_at"), F("offering__duration_minutes"))


class ClassSessionQuerySet(models.QuerySet):
    def for_venue(self, venue):
        return self.filter(offering__venue=venue)

    def live(self):
        return self.filter(cancelled_at__isnull=True)

    def in_window(self, start, end):
        return self.annotate(derived_end=derived_end()).filter(
            starts_at__lt=end, derived_end__gt=start
        )


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

    def save(self, *args, **kwargs):
        # Offerings are single-row domain objects: validate on every ORM
        # write so the teacher-role invariant holds. Bulk writes and raw
        # SQL skip save() and must call full_clean() themselves.
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.teacher_id is None or self.venue_id is None:
            return
        from organizations.models import OrgRole

        venue = self.venue
        covering = OrgRole.objects.filter(
            user_id=self.teacher_id,
            role=OrgRole.Role.TEACHER,
        ).covering(venue)
        if not covering.exists():
            raise ValidationError(
                {"teacher": "Teacher holds no Teacher role covering this venue."},
            )

    def __str__(self):
        return f"{self.title} ({self.category})"


class ClassSession(models.Model):
    """The "when": one occurrence of an offering. End derives from start
    plus the offering duration — never stored, so the two cannot disagree."""

    objects = ClassSessionQuerySet.as_manager()

    offering = models.ForeignKey(
        ClassOffering, on_delete=models.CASCADE, related_name="sessions"
    )
    starts_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=15)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.offering.duration_minutes)

    def __str__(self):
        title = self.offering.title
        day = self.starts_at.strftime("%Y-%m-%d %H:%M")
        return f"{title} · {day}"
