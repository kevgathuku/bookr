"""Read-only door decision. No credit moves here; booking already spent.

Cache is latency only (TTL 60s): every identified attempt still logs,
passback replays excepted. Any DB failure denies (fail-closed).
"""

from datetime import timedelta

from django.core.cache import cache
from django.db.models import F, Q
from django.utils import timezone
from prometheus_client import Counter

from access.models import AccessEvent
from booking.models import ACTIVE_STATUSES, Booking
from organizations.models import Membership
from passes.models import MemberPass

grants_total = Counter("door_grants_total", "Granted door checks", ["venue_id"])

CACHE_TTL_SECONDS = 60
ENTRY_WINDOW_MINUTES = 15
STAFF_ROLES = ("owner", "manager", "teacher", "frontdesk")


def decide(access_point, member):
    """(granted, reason, booking_or_None). Raises on DB outage."""
    replay = _passback(access_point, member)
    if replay is not None:
        return replay[0], "passback_replay", None
    key = f"door:{access_point.pk}:{member.pk}"
    cached = cache.get(key)
    if cached is None:
        return _store(access_point, member, key)
    return (
        cached["granted"],
        cached["reason"],
        Booking.objects.filter(pk=cached["booking_id"]).first(),
    )


def _store(access_point, member, key):
    verdict = _evaluate(access_point, member)
    booking = verdict[2]
    cache.set(
        key,
        {
            "granted": verdict[0],
            "reason": verdict[1],
            "booking_id": booking.pk if booking else None,
        },
        CACHE_TTL_SECONDS,
    )
    return verdict


def _passback(access_point, member):
    last = (
        AccessEvent.objects.filter(access_point=access_point, member=member)
        .order_by("-occurred_at")
        .first()
    )
    if last is None or last.reason == "passback_replay":
        return None
    cutoff = timezone.now() - timedelta(seconds=access_point.passback_seconds)
    if last.occurred_at < cutoff:
        return None
    return last.granted, last.reason


def _evaluate(access_point, member):
    venue = access_point.venue
    now = timezone.now()
    if (
        MemberPass.objects.filter(
            member=member,
            status=MemberPass.Status.ACTIVE,
            valid_from__lte=now,
            valid_until__gte=now,
        )
        .exclude(credits_total__isnull=False, credits_used__gte=F("credits_total"))
        .exists()
    ):
        return True, "active_pass", None
    booking = _live_booking(member, venue, now)
    if booking is not None:
        return True, "live_booking", booking
    if Membership.objects.filter(
        Q(venue__isnull=True, organization=venue.organization) | Q(venue=venue),
        user=member,
        role__in=STAFF_ROLES,
    ).exists():
        return True, "staff", None
    return False, "no_access", None


def _live_booking(member, venue, now):
    for booking in _bookings(member, venue, True):
        target = booking.scheduled_class
        if _window_ok(target.starts_at, target.ends_at, now):
            return booking
    for booking in _bookings(member, venue, False):
        target = booking.appointment
        if _window_ok(target.starts_at, target.ends_at, now):
            return booking
    return None


def _bookings(member, venue, classes):
    found = Booking.objects.filter(
        venue=venue, member=member, status__in=ACTIVE_STATUSES
    )
    if classes:
        return found.filter(scheduled_class__isnull=False).select_related(
            "scheduled_class"
        )
    return found.filter(appointment__isnull=False).select_related("appointment")


def _window_ok(starts, ends, now):
    span = ends - starts
    return starts - timedelta(minutes=ENTRY_WINDOW_MINUTES) <= now <= starts + span
