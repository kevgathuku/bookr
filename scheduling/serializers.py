from typing import ClassVar

from rest_framework import serializers

from scheduling.models import ScheduledClass, TeacherSubstitution


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


class TeacherSubstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherSubstitution
        fields: ClassVar[list[str]] = [
            "id",
            "scheduled_class",
            "old_teacher",
            "new_teacher",
            "reason",
            "created_by",
        ]
        read_only_fields: ClassVar[list[str]] = ["old_teacher", "created_by"]

    def validate(self, attrs):
        klass = attrs["scheduled_class"]
        if klass.status != ScheduledClass.Status.SCHEDULED:
            raise serializers.ValidationError(
                "Only scheduled classes can change teacher."
            )
        if attrs["new_teacher"] == klass.teacher:
            raise serializers.ValidationError("New teacher must differ from current.")
        return attrs
