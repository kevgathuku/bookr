from typing import ClassVar

from rest_framework import serializers

from scheduling.models import ClassType, Room, ScheduledClass, TeacherSubstitution


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields: ClassVar[list[str]] = ["id", "name", "capacity"]


class ClassTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassType
        fields: ClassVar[list[str]] = [
            "id",
            "name",
            "description",
            "capacity_default",
            "duration_min",
        ]


class ScheduledClassSerializer(serializers.ModelSerializer):
    capacity = serializers.ReadOnlyField()
    class_type_name = serializers.CharField(source="class_type.name", read_only=True)
    room_name = serializers.CharField(source="room.name", read_only=True)
    teacher_name = serializers.CharField(source="teacher.username", read_only=True)

    class Meta:
        model = ScheduledClass
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "class_type",
            "class_type_name",
            "room",
            "room_name",
            "teacher",
            "teacher_name",
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
