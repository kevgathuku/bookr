from typing import ClassVar

from rest_framework import serializers

from scheduling.catalogue import ClassOffering, ClassSession


class GenerateSessionsSerializer(serializers.Serializer):
    rrule = serializers.CharField()
    after = serializers.DateTimeField()
    before = serializers.DateTimeField()
    capacity = serializers.IntegerField(min_value=1, required=False)


class SessionCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False)


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
