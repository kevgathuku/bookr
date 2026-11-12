"""Session scheduling: overlap protection the schema cannot express.

Ends derive from start plus offering duration, so no exclusion constraint
can see them. Overlap is checked here against the derived windows, with
the offering row locked so concurrent creates for one offering serialize.
Cross-offering teacher clashes are checked best-effort: admin-created
sessions are not a hot race path.
"""

from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from scheduling.models import ClassOffering, ClassSession


@transaction.atomic
def schedule_session(*, offering, starts_at, capacity=None):
    """Create a session if it overlaps nothing. Raises ValidationError."""
    offering = (
        ClassOffering.objects.select_for_update()
        .select_related("venue")
        .get(pk=offering.pk)
    )
    starts_at = _ensure_aware(starts_at, offering)
    end = starts_at + offering.duration
    _reject_overlap(offering, starts_at, end)
    fields = {"offering": offering, "starts_at": starts_at}
    if capacity is not None:
        fields["capacity"] = capacity
    return ClassSession.objects.create(**fields)


GENERATE_LIMIT = 200


@transaction.atomic
def generate_sessions(*, offering, rrule, after, before, capacity=None):
    """Expand an RFC recurrence rule into sessions, all or nothing.

    Occurrences outside [after, before) are skipped; a clash anywhere
    aborts the whole batch so retries never half-create a series."""
    wanted = [
        occurrence
        for occurrence in _expand(rrule, offering)
        if after <= occurrence < before
    ]
    if len(wanted) > GENERATE_LIMIT:
        raise ValidationError(f"More than {GENERATE_LIMIT} sessions in window.")
    return [
        schedule_session(offering=offering, starts_at=start, capacity=capacity)
        for start in wanted
    ]


def _expand(rrule, offering):
    try:
        occurrences = list(rrulestr(rrule))
    except ValueError as error:
        raise ValidationError(f"Bad recurrence rule: {error}")
    tz = ZoneInfo(offering.venue.time_zone or "UTC")
    return [
        timezone.make_aware(occurrence, tz)
        if timezone.is_naive(occurrence)
        else occurrence
        for occurrence in occurrences
    ]


def _ensure_aware(starts_at, offering):
    if timezone.is_naive(starts_at):
        tz = ZoneInfo(offering.venue.time_zone or "UTC")
        return timezone.make_aware(starts_at, tz)
    return starts_at


def _reject_overlap(offering, starts_at, end):
    window = offering.duration
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
            longest=models.Max("duration")
        )["longest"]
        or offering.duration
    )
    candidates = (
        ClassSession.objects.select_related("offering")
        .filter(
            offering__teacher=offering.teacher,
            cancelled_at__isnull=True,
            starts_at__lt=end,
            starts_at__gt=starts_at - longest,
        )
        .exclude(offering=offering)
    )
    for session in candidates:
        other_end = session.starts_at + session.offering.duration
        if session.starts_at < end and starts_at < other_end:
            raise ValidationError("Teacher is already booked at this time.")
