from datetime import timedelta
from typing import ClassVar

from django.db import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound

from organizations.permissions import IsStaffOrReadOnly, IsVenueMember
from scheduling.models import ScheduledClass, TeacherSubstitution
from scheduling.serializers import (
    ScheduledClassSerializer,
    TeacherSubstitutionSerializer,
)

MAX_WINDOW = timedelta(days=31)


class TeacherSubstitutionViewSet(viewsets.ModelViewSet):
    """History kept: list/retrieve/create, never update/delete."""

    serializer_class = TeacherSubstitutionSerializer
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaffOrReadOnly,
    ]
    http_method_names: ClassVar[list[str]] = [  # type: ignore[misc]
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        return TeacherSubstitution.objects.filter(
            scheduled_class__venue=self.request.venue
        ).select_related("scheduled_class", "old_teacher", "new_teacher")

    def perform_create(self, serializer):
        from django.db import transaction

        klass = serializer.validated_data["scheduled_class"]
        if klass.venue != self.request.venue:
            raise NotFound("No such venue.")
        with transaction.atomic():
            locked = ScheduledClass.objects.select_for_update().get(pk=klass.pk)
            old_teacher = locked.teacher
            locked.teacher = serializer.validated_data["new_teacher"]
            locked.save()
            serializer.save(old_teacher=old_teacher, created_by=self.request.user)


def parse_window_bound(value, default):
    if value is None:
        return default
    try:
        parsed = parse_datetime(value)
    except ValueError, TypeError:
        raise serializers.ValidationError("Window bounds must be datetimes.")
    if parsed is None:
        raise serializers.ValidationError("Window bounds must be datetimes.")
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


class ScheduledClassViewSet(viewsets.ModelViewSet):
    serializer_class = ScheduledClassSerializer
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaffOrReadOnly,
    ]

    def get_queryset(self):
        venue_classes = (
            ScheduledClass.objects.for_venue(self.request.venue)
            .select_related("class_type", "room", "teacher")
            .order_by("starts_at")
        )
        start, end = self._window()
        return venue_classes.filter(starts_at__lt=end, ends_at__gt=start)

    def create(self, request, *args, **kwargs):
        try:
            created = super().create(request, *args, **kwargs)
        except IntegrityError:
            # Exclusion constraint (room/teacher overlap) refused at the DB.
            raise serializers.ValidationError(
                "Overlaps an existing class for this room or teacher.",
            )
        return created

    def perform_create(self, serializer):
        # A crafted venue id in the payload must not escape the request venue.
        payload_venue = serializer.validated_data["venue"]
        if payload_venue != self.request.venue:
            raise NotFound("No such venue.")
        serializer.save()

    def _window(self):
        params = self.request.query_params
        start = parse_window_bound(params.get("from"), timezone.now())
        end = parse_window_bound(params.get("to"), start + MAX_WINDOW)
        if end <= start or end - start > MAX_WINDOW:
            raise serializers.ValidationError("Window must span 1s to 31d.")
        return start, end
