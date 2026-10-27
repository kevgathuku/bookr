from datetime import date
from typing import ClassVar

from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.permissions import IsVenueMember
from scheduling.appointments import Resource
from scheduling.availability import generate_slots


class AvailabilitySlotsView(APIView):
    """Day slots for one resource. Members may read (future booking flow)."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def get(self, request):
        slots = generate_slots(
            self._resource(request),
            self._day(request),
            self._duration(request),
            teacher=self._teacher(request),
        )
        return Response([{"starts_at": start, "ends_at": end} for start, end in slots])

    def _teacher(self, request):
        teacher_id = request.query_params.get("teacher")
        if teacher_id is None:
            return None
        from django.contrib.auth import get_user_model

        try:
            return get_user_model().objects.get(pk=int(teacher_id))
        except ValueError, get_user_model().DoesNotExist:
            raise serializers.ValidationError("teacher must be a user id.")

    def _resource(self, request):
        try:
            resource = Resource.objects.select_related("venue").get(
                pk=int(request.query_params.get("resource"))
            )
        except TypeError, ValueError, Resource.DoesNotExist:
            raise NotFound("No such venue.")
        if resource.venue != request.venue:
            raise NotFound("No such venue.")
        return resource

    def _day(self, request):
        try:
            return date.fromisoformat(request.query_params.get("date"))
        except TypeError, ValueError:
            raise serializers.ValidationError("date must be YYYY-MM-DD.")

    def _duration(self, request):
        try:
            duration = int(request.query_params.get("duration"))
        except TypeError, ValueError:
            raise serializers.ValidationError("duration must be minutes.")
        if duration <= 0:
            raise serializers.ValidationError("duration must be minutes.")
        return duration
