"""Read-only door decision. No credit moves here; booking already spent.

Cache is latency only (TTL 60s): every identified attempt still logs,
passback replays excepted. Any DB failure denies (fail-closed).
"""

from datetime import timedelta

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from prometheus_client import Counter

from access.models import AccessEvent
from booking.models import ACTIVE_STATUSES, Booking
from organizations.capabilities import can_staff_door, roles_for
from passes.models import Membership, PlanType

grants_total = Counter("door_grants_total", "Granted door checks", ["venue_id"])

CACHE_TTL_SECONDS = 60
ENTRY_WINDOW_MINUTES = 15


def decide(access_point, member):
    """(granted, reason, booking_or_None). Raises on DB outage."""
    replay = _passback(access_point, member)
    if replay is not None:
        return replay[0], "passback_replay", None
    key = f"door:{access_point.pk}:{member.pk}"
    cached = cache.get(key)
    if cached is None:
        return _store(access_point, member, key)
    if cached["booking_id"] is None:
        return cached["granted"], cached["reason"], None
    booking = Booking.objects.filter(pk=cached["booking_id"]).first()
    if booking is None or booking.status in ACTIVE_STATUSES:
        return cached["granted"], cached["reason"], booking
    # Grant went stale (booking cancelled inside the TTL): re-evaluate.
    cache.delete(key)
    return _store(access_point, member, key)


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
    if _has_valid_plan_membership(member, venue, now):
        return True, "active_pass", None
    booking = _live_booking(member, venue, now)
    if booking is not None:
        return True, "live_booking", booking
    if _is_staff(member, venue):
        return True, "staff", None
    return False, "no_access", None


def _has_valid_plan_membership(member, venue, now):
    """Monthly valid within dates, or credit balance remaining within dates."""
    today = now.date()
    return (
        Membership.objects.filter(
            user=member,
            plan__organization=venue.organization,
            starts_on__lte=today,
        )
        .filter(Q(ends_on__gte=today) | Q(ends_on__isnull=True))
        .filter(Q(plan__plan_type=PlanType.MONTHLY) | Q(credits_remaining__gt=0))
        .exists()
    )


def _is_staff(member, venue):
    return can_staff_door(roles_for(member, venue))


def _live_booking(member, venue, now):
    for booking in _bookings(member, venue):
        start = booking.session.starts_at
        end = start + timedelta(minutes=booking.session.offering.duration_minutes)
        if _window_ok(start, end, now):
            return booking
    return None


def _bookings(member, venue):
    return (
        Booking.objects.filter(
            member=member,
            session__offering__venue=venue,
            status__in=ACTIVE_STATUSES,
        )
        .select_related("session", "session__offering")
        .order_by("session__starts_at")
    )


def _window_ok(starts, ends, now):
    span = ends - starts
    return starts - timedelta(minutes=ENTRY_WINDOW_MINUTES) <= now <= starts + span
