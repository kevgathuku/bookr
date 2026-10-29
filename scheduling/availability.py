"""Pure slot computation: weekly rules minus exceptions minus commitments.

Never stored — slots derive on read. All datetimes stored UTC; arithmetic
runs in the venue wall timezone so DST gaps/folds behave (a missing wall
hour simply yields no slot via wall-time dedupe).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def _venue_tz(venue):
    return ZoneInfo(venue.time_zone or "UTC")


def _local_window(venue, day, window):
    tz = _venue_tz(venue)
    start = datetime.combine(day, window.start_time, tzinfo=tz)
    end = datetime.combine(day, window.end_time, tzinfo=tz)
    utc = ZoneInfo("UTC")
    return start.astimezone(utc), end.astimezone(utc)


def _commitments(teacher, resource, day):
    from scheduling.appointments import Appointment
    from scheduling.models import ScheduledClass

    tz = _venue_tz(resource.venue)
    midnight_utc = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(
        ZoneInfo("UTC")
    )
    day_end_utc = midnight_utc + timedelta(days=1)
    busy = list(
        Appointment.objects.filter(
            resource=resource,
            status=Appointment.Status.SCHEDULED,
            starts_at__lt=day_end_utc,
            ends_at__gt=midnight_utc,
        ).values_list("starts_at", "ends_at")
    )
    if teacher is None:
        return busy
    busy.extend(
        ScheduledClass.objects.filter(
            teacher=teacher,
            status=ScheduledClass.Status.SCHEDULED,
            starts_at__lt=day_end_utc,
            ends_at__gt=midnight_utc,
        ).values_list("starts_at", "ends_at")
    )
    busy.extend(
        Appointment.objects.filter(
            teacher=teacher,
            status=Appointment.Status.SCHEDULED,
            starts_at__lt=day_end_utc,
            ends_at__gt=midnight_utc,
        ).values_list("starts_at", "ends_at")
    )
    return busy


def _blocked_windows(resource, day, teacher):
    from scheduling.appointments import AvailabilityException

    try:
        exception = resource.exceptions.get(date=day)
    except AvailabilityException.DoesNotExist:
        exception = None
    if exception is not None and exception.closed:
        return None
    windows = []
    if exception is not None:
        windows.append(_local_window(resource.venue, day, exception))
    from organizations.models import VenuePolicy

    try:
        buffer = timedelta(minutes=resource.venue.current_policy.booking_buffer_minutes)
    except VenuePolicy.DoesNotExist:
        buffer = timedelta(0)
    for start, end in _commitments(teacher, resource, day):
        windows.append((start - buffer, end + buffer))
    return windows


def _candidate_slots(resource, day, step):
    from scheduling.appointments import AvailabilityRule

    for rule in AvailabilityRule.objects.filter(
        resource=resource, weekday=day.weekday()
    ):
        if rule.valid_from and rule.valid_from.date() > day:
            continue
        if rule.valid_until and rule.valid_until.date() < day:
            continue
        window_start, window_end = _local_window(resource.venue, day, rule)
        cursor = window_start
        while cursor + step <= window_end:
            wall = cursor.astimezone(_venue_tz(resource.venue)).replace(tzinfo=None)
            yield wall, (cursor, cursor + step)
            cursor += step


def _slot_free(slot, windows):
    return not any(max(slot[0], span[0]) < min(slot[1], span[1]) for span in windows)


def generate_slots(resource, day, duration_min, teacher=None):
    """List of (start_utc, end_utc) slots for one resource-day."""
    step = timedelta(minutes=duration_min)
    windows = _blocked_windows(resource, day, teacher)
    if windows is None:
        return []
    free = [
        (wall, slot)
        for wall, slot in _candidate_slots(resource, day, step)
        if _slot_free(slot, windows)
    ]
    by_wall = dict(free)
    return [by_wall[wall] for wall in sorted(by_wall)]
