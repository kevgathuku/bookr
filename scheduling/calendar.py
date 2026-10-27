from typing import ClassVar

from rest_framework import generics, serializers

from organizations.permissions import IsVenueMember
from scheduling.appointments import Appointment
from scheduling.models import ScheduledClass
from scheduling.views import MAX_WINDOW, parse_window_bound


class CalendarEventSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.IntegerField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    room = serializers.CharField(allow_null=True)
    teacher = serializers.IntegerField()


class CalendarView(generics.ListAPIView):
    """Merged classes + appointments for a bounded window (31d max)."""

    serializer_class = CalendarEventSerializer
    permission_classes: ClassVar[list] = [IsVenueMember]

    def get_queryset(self):
        # DRF needs a queryset; the merged list is built in list().
        return ScheduledClass.objects.none()

    def list(self, request, *args, **kwargs):
        from django.utils import timezone

        params = request.query_params
        start = parse_window_bound(params.get("from"), timezone.now())
        end = parse_window_bound(params.get("to"), start + MAX_WINDOW)
        if end <= start or end - start > MAX_WINDOW:
            raise serializers.ValidationError("Window must span 1s to 31d.")
        events = self._classes(start, end) + self._appointments(start, end)
        events.sort(key=lambda event: event["starts_at"])
        page = self.paginate_queryset(events)
        if page is not None:
            return self.get_paginated_response(page)
        return self._response(events)

    def _response(self, events):
        from rest_framework.response import Response

        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)

    def _classes(self, start, end):
        classes = (
            ScheduledClass.objects.for_venue(self.request.venue)
            .select_related("class_type", "room", "teacher")
            .filter(starts_at__lt=end, ends_at__gt=start)
            .order_by("starts_at")
        )
        teacher_id = self._int_param("teacher")
        if teacher_id is not None:
            classes = classes.filter(teacher_id=teacher_id)
        room_id = self._int_param("room")
        if room_id is not None:
            classes = classes.filter(room_id=room_id)
        return [
            {
                "kind": "class",
                "id": klass.pk,
                "title": klass.class_type.name,
                "starts_at": klass.starts_at,
                "ends_at": klass.ends_at,
                "room": klass.room.name,
                "teacher": klass.teacher_id,
            }
            for klass in classes
        ]

    def _appointments(self, start, end):
        appointments = (
            Appointment.objects.for_venue(self.request.venue)
            .select_related("resource", "teacher")
            .filter(starts_at__lt=end, ends_at__gt=start)
            .order_by("starts_at")
        )
        teacher_id = self._int_param("teacher")
        if teacher_id is not None:
            appointments = appointments.filter(teacher_id=teacher_id)
        resource_id = self._int_param("resource")
        if resource_id is not None:
            appointments = appointments.filter(resource_id=resource_id)
        return [
            {
                "kind": "appointment",
                "id": appointment.pk,
                "title": appointment.resource.name if appointment.resource else "1-1",
                "starts_at": appointment.starts_at,
                "ends_at": appointment.ends_at,
                "room": None,
                "teacher": appointment.teacher_id,
            }
            for appointment in appointments
        ]

    def _int_param(self, name):
        value = self.request.query_params.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except TypeError, ValueError:
            raise serializers.ValidationError(f"{name} must be an integer.")
