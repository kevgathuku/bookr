from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


def _iana_time_zone(value):
    """IANA names only (stdlib zoneinfo): typos fail instead of silently
    falling back to UTC in venue-time display."""
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError, ValueError, TypeError:
        raise ValidationError(f"Unknown time zone: {value}.")


class Organization(models.Model):
    class Scope(models.TextChoices):
        # SPANNING: one membership covers every venue (membership.venue NULL).
        # PER_VENUE: each membership pins exactly one venue (venue required).
        SPANNING = "spanning", "Spanning"
        PER_VENUE = "per_venue", "Per venue"

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    membership_scope = models.CharField(
        max_length=16, choices=Scope.choices, default=Scope.SPANNING
    )

    @property
    def is_spanning(self):
        return self.membership_scope == self.Scope.SPANNING

    @property
    def is_per_venue(self):
        return self.membership_scope == self.Scope.PER_VENUE

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

    @property
    def current_policy(self):
        policy = VenuePolicy.objects.current(self)
        if policy is None:
            raise VenuePolicy.DoesNotExist("VenuePolicy matching query does not exist.")
        return policy

    def policy_for(self, user):
        """Pinned version for grandfathered holders, else current."""
        memberships = list(
            Membership.objects.filter(user=user).select_related("policy")
        )
        pinned = next((mem for mem in memberships if mem.venue_id == self.pk), None)
        chosen = pinned or next(
            (
                mem
                for mem in memberships
                if mem.venue_id is None and mem.organization_id == self.organization_id
            ),
            None,
        )
        if chosen is not None and chosen.policy_id is not None:
            return chosen.policy
        return self.current_policy

    def __str__(self):
        return f"{self.name} ({self.organization})"


class VenuePolicyManager(models.Manager):
    def activate(self, venue, **fields):
        """Retire the open row (if any) and insert the successor, atomically."""
        with transaction.atomic():
            self.filter(venue=venue, valid_until__isnull=True).update(
                valid_until=timezone.now()
            )
            return self.create(venue=venue, valid_until=None, **fields)

    def current(self, venue):
        """Latest open row: overlapping windows resolve to the newest."""
        return (
            self.filter(venue=venue, valid_until__isnull=True)
            .order_by("-valid_from", "-version")
            .first()
        )


# Business rules, configurable row per venue — policy edits never touch identity rows.
class VenuePolicy(models.Model):
    # Versions, never edits: retire stamps valid_until, activate inserts a row.
    # Overlapping open rows are allowed; holders pin versions explicitly.
    objects = VenuePolicyManager()
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="policies")
    # System-assigned per-venue sequence (Kevin: version field); save() assigns.
    version = models.PositiveIntegerField(default=1)
    valid_from = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class_late_cancel_hours = models.PositiveSmallIntegerField(
        default=8,
        help_text=(
            "Cancel cutoff for group classes; "
            "inside the window the credit is forfeited."
        ),
    )
    appointment_late_cancel_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text=(
            "Cancel cutoff for 1-1 classes; inside the window the credit is forfeited."
        ),
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
        verbose_name_plural = "venue policies"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "version"],
                name="policy_version_unique_per_venue",
            ),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding:
            latest = (
                VenuePolicy.objects.filter(venue=self.venue)
                .order_by("-version")
                .first()
            )
            self.version = latest.version + 1 if latest else 1
        super().save(*args, **kwargs)

    def retire(self):
        """Deactivate this version. Use `activate()` for the retire+insert pair."""
        self.valid_until = timezone.now()
        self.save(update_fields=["valid_until"])

    def __str__(self):
        state = (
            "active"
            if self.valid_until is None
            else f"retired {self.valid_until:%Y-%m-%d}"
        )
        return f"Policy for {self.venue} ({state})"


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
    # NULL: follows the venue's current policy. Set: grandfathered to that
    # version — later activations never move the holder.
    policy = models.ForeignKey(
        VenuePolicy,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="holders",
    )

    def clean(self):
        super().clean()
        if self.organization_id is None:
            return  # null FK flagged separately; nothing to compare yet
        if self.organization.is_spanning and self.venue_id is not None:
            raise ValidationError(
                {"venue": "Spanning memberships must not pin a venue."}
            )
        if self.organization.is_per_venue and self.venue_id is None:
            raise ValidationError({"venue": "Per-venue organizations require a venue."})

    class Meta:
        # NULLs never equal: two spanning rows slip past this — the creation
        # service must also guard one spanning membership per user per org.
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "user", "venue"], name="member_once_per_scope"
            ),
        ]

    def __str__(self):
        where = self.venue.name if self.venue else "all venues"
        return f"{self.user} · {self.role} @ {where}"


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

    def __str__(self):
        where = self.venue.name if self.venue else "all venues"
        return f"{self.user} · {self.role} @ {where}"
