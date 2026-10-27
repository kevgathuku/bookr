import hashlib
import secrets
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from organizations.tenancy import VenueScopedQuerySet


def hash_token(plaintext):
    return hashlib.sha256(plaintext.encode()).hexdigest()


class AccessPoint(models.Model):
    objects = VenueScopedQuerySet.as_manager()
    venue = models.ForeignKey(
        "organizations.Venue", on_delete=models.CASCADE, related_name="access_points"
    )
    name = models.CharField(max_length=200)
    controller_id = models.CharField(max_length=64)
    api_token_hash = models.CharField(max_length=64, default="")
    passback_seconds = models.PositiveIntegerField(default=60)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["venue", "controller_id"],
                name="controller_once_per_venue",
            ),
        ]

    def set_token(self):
        """Rotate the controller secret. Plaintext shown once, hash stored."""
        plaintext = secrets.token_urlsafe(32)
        self.api_token_hash = hash_token(plaintext)
        return plaintext

    def check_token(self, plaintext):
        return bool(self.api_token_hash) and secrets.compare_digest(
            self.api_token_hash, hash_token(plaintext)
        )

    def __str__(self):
        return f"{self.name} @ {self.venue}"


class AccessEvent(models.Model):
    access_point = models.ForeignKey(
        AccessPoint, on_delete=models.CASCADE, related_name="events"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_events",
    )
    granted = models.BooleanField()
    reason = models.CharField(max_length=32)
    booking = models.ForeignKey(
        "booking.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_events",
    )
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering: ClassVar[list[str]] = ["-occurred_at"]

    def __str__(self):
        verdict = "grant" if self.granted else "deny"
        return f"{self.access_point}: {verdict} {self.member} ({self.reason})"
