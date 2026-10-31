"""Partner feed shapes: no staff login names leave the building."""

from typing import ClassVar

from rest_framework import serializers

from scheduling.catalogue import ClassSession


class PartnerSessionSerializer(serializers.ModelSerializer):
    venue = serializers.IntegerField(source="offering.venue_id", read_only=True)
    title = serializers.CharField(source="offering.title", read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ClassSession
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "offering",
            "title",
            "starts_at",
            "ends_at",
            "capacity",
        ]
