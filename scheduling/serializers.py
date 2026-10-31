from typing import ClassVar

from rest_framework import serializers

from scheduling.catalogue import ClassOffering, ClassSession
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
    spots_left = serializers.SerializerMethodField()

    def get_spots_left(self, obj) -> int | None:
        if obj.capacity is None:
            return None
        return max(obj.capacity - (getattr(obj, "booked", 0) or 0), 0)

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
            "spots_left",
        ]


class TeacherSubstitutionSerializer(serializers.ModelSerializer):
    old_teacher_name = serializers.CharField(
        source="old_teacher.username", read_only=True
    )
    new_teacher_name = serializers.CharField(
        source="new_teacher.username", read_only=True
    )

    class Meta:
        model = TeacherSubstitution
        fields: ClassVar[list[str]] = [
            "id",
            "scheduled_class",
            "old_teacher",
            "old_teacher_name",
            "new_teacher",
            "new_teacher_name",
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


class GenerateSessionsSerializer(serializers.Serializer):
    rrule = serializers.CharField()
    after = serializers.DateTimeField()
    before = serializers.DateTimeField()
    capacity = serializers.IntegerField(min_value=1, required=False)


class OfferingSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.username", read_only=True)

    class Meta:
        model = ClassOffering
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "teacher",
            "teacher_name",
            "title",
            "category",
            "duration_minutes",
            "credit_cost",
        ]


class SessionSerializer(serializers.ModelSerializer):
    offering_title = serializers.CharField(source="offering.title", read_only=True)
    category = serializers.CharField(source="offering.category", read_only=True)
    teacher = serializers.IntegerField(source="offering.teacher_id", read_only=True)
    teacher_name = serializers.CharField(
        source="offering.teacher.username", read_only=True
    )
    venue = serializers.IntegerField(source="offering.venue_id", read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    spots_left = serializers.SerializerMethodField()

    def get_spots_left(self, obj) -> int | None:
        if obj.capacity is None:
            return None
        return max(obj.capacity - (getattr(obj, "booked", 0) or 0), 0)

    class Meta:
        model = ClassSession
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "offering",
            "offering_title",
            "category",
            "teacher",
            "teacher_name",
            "starts_at",
            "ends_at",
            "capacity",
            "spots_left",
        ]
