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


class OrgRoleQuerySet(models.QuerySet):
    def covering(self, venue: Venue) -> OrgRoleQuerySet:
        """Rows granting access at `venue`: pinned to it, or org-wide
        within its organization. The organization filter keeps other
        orgs' org-wide rows out."""
        pinned = models.Q(venue=venue)
        org_wide = models.Q(venue__isnull=True)
        return self.filter(pinned | org_wide, organization_id=venue.organization_id)


class OrgRoleType(models.TextChoices):
    """Role ranks; use via OrgRole.Role. Adding one needs a migration: the
    orgrole_role_valid CHECK pins the allowed values. The migration keeps
    explicit literals; the model reads the values here."""

    MEMBER = "member", "Member"
    TEACHER = "teacher", "Teacher"
    FRONTDESK = "frontdesk", "Front desk"
    MANAGER = "manager", "Manager"
    OWNER = "owner", "Owner"


class OrgRole(models.Model):
    """Duties live here, not on User. One user can be a member at one venue
    and a teacher at another. venue=None means the role applies org-wide."""

    # Alias, not a nested definition: Meta's CHECK below needs the values,
    # and class bodies don't see their enclosing class's names.
    Role = OrgRoleType  # noqa: WPS115 — public OrgRole.Role API

    objects = OrgRoleQuerySet.as_manager()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_roles"
    )
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Values live on OrgRoleType; the migration keeps the
            # explicit literals (migrations serialize plain lists).
            models.CheckConstraint(
                condition=models.Q(role__in=OrgRoleType.values),
                name="orgrole_role_valid",
            ),
            # With pinned venue - enforce unique org / user / venue per role
            models.UniqueConstraint(
                fields=["organization", "user", "venue"],
                name="orgrole_one_role_per_slot",
            ),
            # For org-wide roles, ensure uniqueness by org / user
            models.UniqueConstraint(
                fields=["organization", "user"],
                condition=models.Q(venue__isnull=True),
                name="orgrole_one_org_wide_role",
            ),
        ]

    def clean(self):
        # Cross-table coherence has no CHECK equivalent (constraints can't
        # join): writers construct coherent rows (organization matches the
        # venue's), this is the backstop.
        super().clean()
        if self.venue is None or self.organization is None:
            return
        if self.venue.organization_id != self.organization_id:
            raise ValidationError(
                {"venue": "Role venue belongs to another organization."}
            )

    def __str__(self):
        where = self.venue.name if self.venue else "all venues"
        return f"{self.user} · {self.role} @ {where}"
