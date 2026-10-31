"""Session scheduling: overlap protection the schema cannot express.

Ends derive from start plus offering duration, so no exclusion constraint
can see them. Overlap is checked here against the derived windows, with
the offering row locked so concurrent creates for one offering serialize.
Cross-offering teacher clashes are checked best-effort: admin-created
sessions are not a hot race path.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from scheduling.catalogue import ClassOffering, ClassSession


@transaction.atomic
def schedule_session(*, offering, starts_at, capacity=None):
    """Create a session if it overlaps nothing. Raises ValidationError."""
    offering = (
        ClassOffering.objects.select_for_update()
        .select_related("venue")
        .get(pk=offering.pk)
    )
    starts_at = _ensure_aware(starts_at, offering)
    end = starts_at + timedelta(minutes=offering.duration_minutes)
    _reject_overlap(offering, starts_at, end)
    fields = {"offering": offering, "starts_at": starts_at}
    if capacity is not None:
        fields["capacity"] = capacity
    return ClassSession.objects.create(**fields)


def _ensure_aware(starts_at, offering):
    if timezone.is_naive(starts_at):
        tz = ZoneInfo(offering.venue.time_zone or "UTC")
        return timezone.make_aware(starts_at, tz)
    return starts_at


def _reject_overlap(offering, starts_at, end):
    window = timedelta(minutes=offering.duration_minutes)
    clash = ClassSession.objects.filter(
        offering=offering,
        cancelled_at__isnull=True,
        starts_at__lt=end,
        starts_at__gt=starts_at - window,
    ).exists()
    if clash:
        raise ValidationError("Overlaps an existing session of this offering.")
    _reject_teacher_clash(offering, starts_at, end)


def _reject_teacher_clash(offering, starts_at, end):
    longest = (
        ClassOffering.objects.filter(teacher=offering.teacher).aggregate(
            longest=models.Max("duration_minutes")
        )["longest"]
        or offering.duration_minutes
    )
    candidates = (
        ClassSession.objects.select_related("offering")
        .filter(
            offering__teacher=offering.teacher,
            cancelled_at__isnull=True,
            starts_at__lt=end,
            starts_at__gt=starts_at - timedelta(minutes=longest),
        )
        .exclude(offering=offering)
    )
    for session in candidates:
        other_end = session.starts_at + timedelta(
            minutes=session.offering.duration_minutes
        )
        if session.starts_at < end and starts_at < other_end:
            raise ValidationError("Teacher is already booked at this time.")
