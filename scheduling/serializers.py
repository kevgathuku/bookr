from typing import ClassVar

from rest_framework import serializers

from scheduling.models import ScheduledClass


class ScheduledClassSerializer(serializers.ModelSerializer):
    capacity = serializers.ReadOnlyField()

    class Meta:
        model = ScheduledClass
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "class_type",
            "room",
            "teacher",
            "starts_at",
            "ends_at",
            "capacity_override",
            "status",
            "checkin_opens_minutes",
            "capacity",
        ]
