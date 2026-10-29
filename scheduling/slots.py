from datetime import date
from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.permissions import IsVenueMember
from scheduling.appointments import Resource
from scheduling.availability import generate_slots


def resource_or_404(request):
    try:
        resource = Resource.objects.select_related("venue").get(
            pk=int(request.query_params.get("resource"))
        )
    except TypeError, ValueError, Resource.DoesNotExist:
        raise NotFound("No such venue.")
    if resource.venue != request.venue:
        raise NotFound("No such venue.")
    return resource


class SlotSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class AvailabilitySlotsView(APIView):
    """Day slots for one resource. Members may read (future booking flow)."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(
        responses=SlotSerializer(many=True),
        parameters=[
            OpenApiParameter("resource", int),
            OpenApiParameter("date", str, required=False),
            OpenApiParameter("from", str, required=False),
            OpenApiParameter("to", str, required=False),
            OpenApiParameter("duration", int, required=False),
            OpenApiParameter("teacher", int, required=False),
        ],
    )
    def get(self, request):
        resource = resource_or_404(request)
        duration = self._duration(request)
        teacher = self._teacher(request)
        slots = []
        for day in self._days(request):
            slots.extend(generate_slots(resource, day, duration, teacher=teacher))
        slots.sort(key=lambda slot: slot[0])
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
        return resource_or_404(request)

    def _days(self, request):
        from datetime import timedelta

        from django.utils import timezone

        from scheduling.views import MAX_WINDOW, parse_window_bound

        params = request.query_params
        if params.get("date") is not None:
            return [self._day(request)]
        start = parse_window_bound(params.get("from"), timezone.now())
        end = parse_window_bound(params.get("to"), start + MAX_WINDOW)
        if end <= start or end - start > MAX_WINDOW:
            raise serializers.ValidationError("Window must span 1s to 31d.")
        days = []
        cursor = start.date()
        while cursor <= end.date():
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def _day(self, request):
        try:
            return date.fromisoformat(request.query_params.get("date"))
        except TypeError, ValueError:
            raise serializers.ValidationError("date must be YYYY-MM-DD.")

    def _duration(self, request):
        if request.query_params.get("duration") is None:
            return 60
        try:
            duration = int(request.query_params.get("duration"))
        except TypeError, ValueError:
            raise serializers.ValidationError("duration must be minutes.")
        if duration <= 0:
            raise serializers.ValidationError("duration must be minutes.")
        return duration
