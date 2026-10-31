from typing import ClassVar

from rest_framework import generics, serializers

from organizations.permissions import IsVenueMember
from scheduling.catalogue import ClassSession
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
    """Sessions for a bounded window (31d max)."""

    serializer_class = CalendarEventSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    def get_queryset(self):
        # DRF needs a queryset; the list is built in list().
        return ClassSession.objects.none()

    def list(self, request, *args, **kwargs):
        from django.utils import timezone
        from rest_framework.response import Response

        params = request.query_params
        start = parse_window_bound(params.get("from"), timezone.now())
        end = parse_window_bound(params.get("to"), start + MAX_WINDOW)
        if end <= start or end - start > MAX_WINDOW:
            raise serializers.ValidationError("Window must span 1s to 31d.")
        events = self._classes(start, end)
        events.sort(key=lambda event: event["starts_at"])
        page = self.paginate_queryset(events)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(self.get_serializer(events, many=True).data)

    def _classes(self, start, end):
        sessions = ClassSession.objects.for_venue(self.request.venue).live()
        sessions = (
            sessions.in_window(start, end)
            .select_related("offering", "offering__teacher")
            .order_by("starts_at")
        )
        teacher_id = self._int_param("teacher")
        if teacher_id is not None:
            sessions = sessions.filter(offering__teacher_id=teacher_id)
        return [_serialize_session(session) for session in sessions]

    def _int_param(self, name):
        value = self.request.query_params.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except TypeError, ValueError:
            raise serializers.ValidationError(f"{name} must be an integer.")


def _serialize_session(session):
    return {
        "kind": "session",
        "id": session.pk,
        "title": session.offering.title,
        "starts_at": session.starts_at,
        "ends_at": session.ends_at,
        "room": None,
        "teacher": session.offering.teacher_id,
    }
