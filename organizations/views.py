from typing import ClassVar

from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import VenuePolicy
from organizations.permissions import IsStaff, IsVenueMember


class VenuePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = VenuePolicy
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "valid_from",
            "valid_until",
            "class_late_cancel_hours",
            "appointment_late_cancel_hours",
            "forfeit_late_cancel",
            "waitlist_hold_minutes",
            "booking_buffer_minutes",
        ]


class PolicyListView(generics.ListAPIView):
    """Version history, newest first. Staff only; versions never edit."""

    serializer_class = VenuePolicySerializer
    permission_classes: ClassVar[list] = [IsVenueMember, IsStaff]  # type: ignore[misc]  # DRF stubs declare these as instance vars

    def get_queryset(self):
        return VenuePolicy.objects.filter(venue=self.request.venue).order_by(
            "-valid_from"
        )


class ActivateSerializer(serializers.Serializer):
    class_late_cancel_hours = serializers.IntegerField(required=False)
    appointment_late_cancel_hours = serializers.IntegerField(required=False)
    forfeit_late_cancel = serializers.BooleanField(required=False)
    waitlist_hold_minutes = serializers.IntegerField(required=False)
    booking_buffer_minutes = serializers.IntegerField(required=False)


class PolicyActivateView(APIView):
    """Retire the open version + insert the successor, atomically."""

    permission_classes: ClassVar[list] = [IsVenueMember, IsStaff]  # type: ignore[misc]  # DRF stubs declare these as instance vars

    def post(self, request):
        form = ActivateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        policy = VenuePolicy.objects.activate(request.venue, **form.validated_data)
        return Response(VenuePolicySerializer(policy).data, status=201)
