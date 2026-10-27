"""Partner feed shapes: no staff login names leave the building."""

from typing import ClassVar

from rest_framework import serializers

from scheduling.models import ScheduledClass


class PartnerClassSerializer(serializers.ModelSerializer):
    class_type_name = serializers.CharField(source="class_type.name", read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True)
    capacity = serializers.ReadOnlyField()

    class Meta:
        model = ScheduledClass
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "class_type",
            "class_type_name",
            "room_name",
            "starts_at",
            "ends_at",
            "status",
            "capacity",
        ]
