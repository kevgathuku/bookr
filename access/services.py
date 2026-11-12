"""Read-only door decision. No credit moves here; booking already spent.

Cache is latency only (TTL 60s): every identified attempt still logs,
passback replays excepted. Any DB failure denies (fail-closed).
"""

import dataclasses
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from access.models import AccessEvent
from booking.models import ACTIVE_STATUSES, Booking
from organizations.capabilities import is_duty_staff, roles_for
from passes.models import Entitlement
from passes.services import valid_memberships

CACHE_TTL_SECONDS = 60
ENTRY_WINDOW_MINUTES = 15


@dataclasses.dataclass(frozen=True)
class DoorVerdict:
    """One door decision: open or not, why, and the booking behind a
    booking-based grant (None for pass, staff, and deny reasons)."""

    granted: bool
    reason: str
    booking: Booking | None


def decide(access_point, member):
    """Decide the door. Raises on DB outage."""
    replay = _passback(access_point, member)
    if replay is not None:
        return DoorVerdict(granted=replay[0], reason="passback_replay", booking=None)
    key = f"door:{access_point.pk}:{member.pk}"
    cached = cache.get(key)
    if cached is None:
        return _store(access_point, member, key)
    if cached["booking_id"] is None:
        return DoorVerdict(
            granted=cached["granted"], reason=cached["reason"], booking=None
        )
    booking = Booking.objects.filter(pk=cached["booking_id"]).first()
    if booking is None or booking.status in ACTIVE_STATUSES:
        return DoorVerdict(
            granted=cached["granted"], reason=cached["reason"], booking=booking
        )
    # Grant went stale (booking cancelled inside the TTL): re-evaluate.
    cache.delete(key)
    return _store(access_point, member, key)


def _store(access_point, member, key):
    verdict = _evaluate(access_point, member)
    booking = verdict.booking
    cache.set(
        key,
        {
            "granted": verdict.granted,
            "reason": verdict.reason,
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
        return DoorVerdict(granted=True, reason="active_pass", booking=None)
    booking = _live_booking(member, venue, now)
    if booking is not None:
        return DoorVerdict(granted=True, reason="live_booking", booking=booking)
    if _is_staff(member, venue):
        return DoorVerdict(granted=True, reason="staff", booking=None)
    return DoorVerdict(granted=False, reason="no_access", booking=None)


def _has_valid_plan_membership(member, venue, now):
    """Unlimited valid within dates, or credit balance remaining within dates."""
    return (
        valid_memberships(member, venue.organization, now.date())
        .filter(
            Q(plan__entitlement=Entitlement.UNLIMITED) | Q(credits_remaining__gt=0),
        )
        .exists()
    )


def _is_staff(member, venue):
    return is_duty_staff(roles_for(member, venue))


def _live_booking(member, venue, now):
    for booking in _bookings(member, venue):
        start = booking.session.starts_at
        end = start + timedelta(minutes=booking.session.offering.duration_minutes)
        if _window_ok(start, end, now):
            return booking
    return None


def _bookings(member, venue):
    # Door seats are claimed seats: held-but-unconfirmed rows grant nothing.
    return (
        Booking.objects.filter(
            member=member,
            session__offering__venue=venue,
            status=Booking.Status.BOOKED,
        )
        .select_related("session", "session__offering")
        .order_by("session__starts_at")
    )


def _window_ok(starts, ends, now):
    span = ends - starts
    return starts - timedelta(minutes=ENTRY_WINDOW_MINUTES) <= now <= starts + span
