from typing import ClassVar

from rest_framework import serializers

from booking.models import Booking
from scheduling.models import ScheduledClass


class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "scheduled_class",
            "appointment",
            "status",
            "source",
            "hold_until",
            "created_at",
        ]


class BookSerializer(serializers.Serializer):
    scheduled_class = serializers.PrimaryKeyRelatedField(
        queryset=ScheduledClass.objects.all()
    )
    idempotency_key = serializers.CharField(max_length=64)
    waitlist = serializers.BooleanField(default=False)
