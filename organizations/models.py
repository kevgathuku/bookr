from typing import ClassVar

from django.conf import settings
from django.db import models


class Organization(models.Model):
    class Scope(models.TextChoices):
        SPANNING = "spanning", "Spanning"
        PER_VENUE = "per_venue", "Per venue"

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    membership_scope = models.CharField(
        max_length=16, choices=Scope.choices, default=Scope.SPANNING
    )


class Venue(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="venues"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    time_zone = models.CharField(max_length=64, default="UTC")

    class Meta:
        constraints: ClassVar[list[models.UniqueConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="venue_slug_unique_per_org"
            ),
        ]


# Business rules, configurable row per venue — policy edits never touch identity rows.
class VenuePolicy(models.Model):
    # Versions, never edits: retire stamps valid_until, activate inserts a row.
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="policies")
    valid_from = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class_late_cancel_hours = models.PositiveSmallIntegerField(
        default=8,
        help_text="Cancel cutoff for group classes; inside the window the credit is forfeited.",
    )
    appointment_late_cancel_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text="Cancel cutoff for 1-1 classes; inside the window the credit is forfeited.",
    )
    forfeit_late_cancel = models.BooleanField(default=True)
    waitlist_hold_minutes = models.PositiveSmallIntegerField(
        default=60,
        help_text=(
            "Window allowed for holding a place in the waitlist pending member confirmation"
        ),
    )
    booking_buffer_minutes = models.PositiveSmallIntegerField(
        default=10,
        help_text=("Buffer allowed between successive bookings"),
    )

    class Meta:
        constraints: ClassVar[list[models.UniqueConstraint]] = [
            models.UniqueConstraint(
                fields=["venue"],
                condition=models.Q(valid_until__isnull=True),
                name="one_active_policy_per_venue",
            ),
        ]


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        TEACHER = "teacher", "Teacher"
        FRONTDESK = "frontdesk", "Front desk"
        MEMBER = "member", "Member"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    # NULL: organization rule applied across all venues
    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
