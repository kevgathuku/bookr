from typing import ClassVar

from rest_framework import serializers

from booking.models import Booking, CancellationPolicy, CancellationRecord
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
            "checked_in_at",
            "created_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = CancellationPolicy
        fields: ClassVar[list[str]] = [
            "id",
            "organization",
            "venue",
            "class_category",
            "plan_type",
            "late_cancel_hours",
            "enforcement",
            "priority",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = CancellationRecord
        fields: ClassVar[list[str]] = [
            "id",
            "booking",
            "member",
            "cause",
            "was_late",
            "enforcement_applied",
            "penalty_waived",
            "waived_by",
            "credits_refunded",
            "snapshot",
            "created_at",
        ]
        read_only_fields: ClassVar[list[str]] = fields


class CancelBookingSerializer(serializers.Serializer):
    # Desk-UI spelling of the initiator flag: staff acting for the member.
    staff_override = serializers.BooleanField(default=False)
    waive_penalty = serializers.BooleanField(default=False)
    reason = serializers.CharField(allow_blank=True, default="")


class WaiveSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False)


class BookSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=ClassSession.objects.all())
