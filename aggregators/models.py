from typing import ClassVar

from django.conf import settings
from django.db import models


class Aggregator(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    api_token_hash = models.CharField(max_length=128)
    seat_allotment = models.PositiveIntegerField()
    cancel_cutoff_minutes = models.PositiveIntegerField(default=60)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    active = models.BooleanField(default=True)
    webhook_url = models.URLField(blank=True, default="")
    webhook_secret = models.CharField(max_length=128, blank=True, default="")
    service_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="aggregator_channels",
    )

    def __str__(self):
        return self.slug


class AggregatorBooking(models.Model):
    aggregator = models.ForeignKey(
        Aggregator, on_delete=models.CASCADE, related_name="bookings"
    )
    external_id = models.CharField(max_length=128)
    booking = models.OneToOneField(
        "booking.Booking", on_delete=models.CASCADE, related_name="aggregator_link"
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["aggregator", "external_id"],
                name="aggregator_external_id_unique",
            )
        ]


class AggregatorEventLog(models.Model):
    aggregator = models.ForeignKey(
        Aggregator, on_delete=models.CASCADE, related_name="event_log"
    )
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=256)
    status_code = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
