from typing import ClassVar

from django.contrib.auth import get_user_model
from rest_framework import serializers

from access.models import AccessEvent, AccessPoint

User = get_user_model()


class CheckSerializer(serializers.Serializer):
    access_point = serializers.PrimaryKeyRelatedField(
        queryset=AccessPoint.objects.all()
    )
    member = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


class CheckResultSerializer(serializers.Serializer):
    granted = serializers.BooleanField()
    reason = serializers.CharField()


class AccessEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessEvent
        fields: ClassVar[list[str]] = [
            "id",
            "access_point",
            "member",
            "granted",
            "reason",
            "booking",
            "occurred_at",
        ]
