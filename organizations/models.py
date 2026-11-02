from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def _iana_time_zone(value):
    """IANA names only (stdlib zoneinfo): typos fail instead of silently
    falling back to UTC in venue-time display."""
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError, ValueError, TypeError:
        raise ValidationError(f"Unknown time zone: {value}.")


class Organization(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Venue(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="venues"
    )
    slug = models.SlugField()
    name = models.CharField(max_length=200)
    time_zone = models.CharField(
        max_length=64, default="UTC", validators=[_iana_time_zone]
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="venue_slug_unique_per_org"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.organization})"


class OrgRole(models.Model):
    """Duties live here, not on User. One user can be a member at one venue
    and a teacher at another. venue=None means the role applies org-wide."""

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        TEACHER = "teacher", "Teacher"
        FRONTDESK = "frontdesk", "Front desk"
        MANAGER = "manager", "Manager"
        OWNER = "owner", "Owner"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_roles"
    )
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices)

    def clean(self):
        super().clean()
        if self.venue_id is None or self.organization_id is None:
            return
        if self.venue.organization_id != self.organization_id:
            raise ValidationError(
                {"venue": "Role venue belongs to another organization."}
            )

    def __str__(self):
        where = self.venue.name if self.venue else "all venues"
        return f"{self.user} · {self.role} @ {where}"
