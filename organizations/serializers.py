from rest_framework import serializers


class MeMembershipSerializer(serializers.Serializer):
    organization = serializers.CharField()
    venue = serializers.CharField(allow_null=True)
    role = serializers.CharField()


class MeVenueSerializer(serializers.Serializer):
    organization = serializers.CharField()
    slug = serializers.CharField()
    name = serializers.CharField()


class MeSerializer(serializers.Serializer):
    username = serializers.CharField()
    memberships = MeMembershipSerializer(many=True)
    venues = MeVenueSerializer(many=True)
