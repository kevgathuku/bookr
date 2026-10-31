from typing import ClassVar

from rest_framework import serializers

from booking.models import Booking
from scheduling.catalogue import ClassSession


class BookingSerializer(serializers.ModelSerializer):
    session_title = serializers.CharField(
        source="session.offering.title", read_only=True
    )
    member_name = serializers.CharField(source="member.username", read_only=True)

    class Meta:
        model = Booking
        fields: ClassVar[list[str]] = [
            "id",
            "session",
            "session_title",
            "member",
            "member_name",
            "membership",
            "credits_spent",
            "status",
            "created_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class BookSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=ClassSession.objects.all())
