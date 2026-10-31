"""Smoke journeys against the live app: schedule → book → ledger →
cancel (refund or late forfeit) → door; plus partner channel idempotency.

Each test composes small given/when helpers (`_given_session`,
`_as_member`, `_book`, `_cancel`) so scenarios read as setup → act →
assert. Smoke must stay fast and deterministic, never share hidden
state between tests.
"""

from datetime import timedelta
from typing import NamedTuple

import pytest
import requests
from django.utils import timezone

pytestmark = [pytest.mark.smoke, pytest.mark.django_db(transaction=True)]

ORG_SLUG = "e2e-run"
VENUE_SLUG = "main"
PASSWORD = "password"


def _session(base_url, token=None, venue=True):
    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    if venue:
        session.headers["X-Venue-Slug"] = VENUE_SLUG
    return session


def _login(base_url, username):
    anonymous = _session(base_url, venue=False)
    response = anonymous.post(
        f"{base_url}/api/v1/auth/token/",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return _session(base_url, token=response.json()["access"])


class _Stage(NamedTuple):
    """Logged-in member client bound to the API root."""

    api: str
    client: requests.Session


def _as_member(base_url, username):
    """Given a main-venue member: stage to act with."""
    return _Stage(f"{base_url}/api/v1", _login(base_url, username))


def _upcoming(stage):
    """Upcoming sessions from the seeded schedule."""
    start = timezone.now()
    end = start + timedelta(days=7)
    listed = stage.client.get(
        f"{stage.api}/sessions/",
        params={"from": start.isoformat(), "to": end.isoformat()},
    )
    assert listed.status_code == 200
    upcoming = [
        session
        for session in listed.json()
        if session["starts_at"] > timezone.now().isoformat()
    ]
    assert upcoming, "seed must provide a future session"
    return upcoming


def _try_book(stage, upcoming):
    """First bookable session id; the seed overbooks, so retry a few."""
    for session in upcoming[:3]:
        attempt = stage.client.post(
            f"{stage.api}/bookings/", json={"session": session["id"]}
        )
        if attempt.status_code == 201:
            return attempt.json()["id"]
    raise AssertionError("no bookable upcoming session")


def _book(stage, session_id, waitlist=False):
    """Book a seat; the created payload (201 asserted here, it is setup)."""
    url = f"{stage.api}/bookings/"
    if waitlist:
        url = f"{url}?waitlist=true"
    booked = stage.client.post(url, json={"session": session_id})
    assert booked.status_code == 201, booked.text
    return booked.json()


def _cancel(stage, booking_id):
    response = stage.client.post(f"{stage.api}/bookings/{booking_id}/cancel/", json={})
    assert response.status_code == 200, response.text
    return response.json()


def _mine(stage, booking_id):
    mine = stage.client.get(f"{stage.api}/bookings/me/", params={"mine": "true"})
    assert mine.status_code == 200, mine.text
    return next(booking for booking in mine.json() if booking["id"] == booking_id)


def _ledger_entry(stage, booking_id, reason):
    ledger = stage.client.get(f"{stage.api}/ledger/")
    assert ledger.status_code == 200, ledger.text
    return next(
        (
            entry
            for entry in ledger.json()
            if entry["booking"] == booking_id and entry["reason"] == reason
        ),
        None,
    )


def test_login_and_schedule(base_url):
    member = _as_member(base_url, f"{ORG_SLUG}-member")

    assert _upcoming(member) != []


def test_calendar_matches_session_list(base_url):
    member = _as_member(base_url, f"{ORG_SLUG}-member")
    start = timezone.now()
    end = start + timedelta(days=7)
    params = {"from": start.isoformat(), "to": end.isoformat()}

    listed = member.client.get(f"{member.api}/sessions/", params=params)
    assert listed.status_code == 200
    events = member.client.get(f"{member.api}/calendar/", params=params)
    assert events.status_code == 200
    session_events = [event for event in events.json() if event["kind"] == "session"]
    assert {event["id"] for event in session_events} == {
        session["id"] for session in listed.json()
    }


def test_book_debits_and_lists(base_url):
    member = _as_member(base_url, f"{ORG_SLUG}-member")
    booking_id = _try_book(member, _upcoming(member))

    booked = _mine(member, booking_id)
    assert booked["status"] == "booked"
    assert booked["credits_spent"] > 0


def test_door_grants_member_denies_stranger(base_url):
    from django.contrib.auth import get_user_model

    from access.models import AccessPoint

    users = get_user_model().objects
    point = AccessPoint.objects.filter(venue__slug=VENUE_SLUG).first()
    assert point is not None
    token = point.set_token()
    point.save()
    door = requests.Session()
    door.headers.update(
        {"Content-Type": "application/json", "Authorization": f"Token {token}"}
    )
    member_id = users.get(username=f"{ORG_SLUG}-member").pk
    stranger_id = users.get(username=f"{ORG_SLUG}-stranger").pk

    check = f"{base_url}/api/access/check/"
    granted = door.post(
        check,
        json={"access_point": point.pk, "member": member_id},
    )
    denied = door.post(
        check,
        json={"access_point": point.pk, "member": stranger_id},
    )

    assert granted.json()["granted"] is True
    assert denied.json()["granted"] is False


def _partner_client(base_url, slug="e2e-partner", allotment=1):
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from aggregators.models import Aggregator
    from aggregators.tokens import new_token
    from scheduling.catalogue import ClassSession

    api = f"{base_url}/api/v1"
    service_user = get_user_model().objects.create_user(username=f"svc-{slug}")
    raw, token_hash = new_token()
    partner = Aggregator.objects.create(
        slug=slug,
        name=slug.title(),
        api_token_hash=token_hash,
        seat_allotment=allotment,
        service_user=service_user,
    )
    session = (
        ClassSession.objects.filter(
            offering__venue__organization__slug=ORG_SLUG,
            starts_at__gt=timezone.now(),
            cancelled_at__isnull=True,
        )
        .order_by("starts_at")
        .first()
    )
    assert session is not None, "seed must provide a future session"
    client = requests.Session()
    client.headers.update({"Content-Type": "application/json", "X-Partner-Token": raw})
    return partner, session, client, f"{api}/aggregators/{slug}/bookings/"


def test_partner_channel_idempotent(base_url):
    from aggregators.models import AggregatorBooking

    partner, session, partner_client, url = _partner_client(base_url)

    first = partner_client.post(url, json={"session": session.pk, "external_id": "e1"})
    second = partner_client.post(url, json={"session": session.pk, "external_id": "e1"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert AggregatorBooking.objects.filter(aggregator=partner).count() == 1


def test_partner_channel_capped_rotated(base_url):
    from aggregators.tokens import rotate

    partner, session, partner_client, url = _partner_client(base_url, slug="e2e-cap")

    over = partner_client.post(url, json={"session": session.pk, "external_id": "e2"})
    assert over.status_code == 201
    full = partner_client.post(url, json={"session": session.pk, "external_id": "e3"})
    assert full.status_code == 409

    _fresh_raw, fresh_hash = rotate()
    partner.api_token_hash = fresh_hash
    partner.save(update_fields=["api_token_hash"])
    stale = partner_client.post(url, json={"session": session.pk, "external_id": "e4"})
    assert stale.status_code == 401


def _given_session(title, starts_in_hours, capacity=None):
    """Committed session in the main venue; capacity only when passed."""
    from django.contrib.auth import get_user_model

    from organizations.models import Venue
    from tests.factories import ClassOfferingFactory, ClassSessionFactory

    venue = Venue.objects.get(organization__slug=ORG_SLUG, slug="main")
    teacher = get_user_model().objects.get(username="e2e-run-teacher")
    offering = ClassOfferingFactory(venue=venue, teacher=teacher, title=title)
    starts_at = timezone.now() + timedelta(hours=starts_in_hours)
    if capacity is not None:
        return ClassSessionFactory(
            offering=offering, starts_at=starts_at, capacity=capacity
        )
    return ClassSessionFactory(offering=offering, starts_at=starts_at)


def _given_member(username, venue):
    """Credited member of the venue's org."""
    from organizations.management.seed_helpers import booker_membership
    from organizations.models import OrgRole
    from tests.factories import user_with_role

    user = user_with_role(venue, OrgRole.Role.MEMBER, username=username, org_wide=True)
    # Factories leave an unusable password; the login flow needs the known one.
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    booker_membership(venue, user)
    return user


def _given_policy(organization, enforcement):
    """Org-wide cancellation rule (default 12h late window)."""
    from tests.factories import CancellationPolicyFactory

    return CancellationPolicyFactory(organization=organization, enforcement=enforcement)


def test_waitlist_queue_returns_waitlisted(base_url):
    session = _given_session("Tiny Spin", starts_in_hours=24, capacity=1)
    _given_member("wl-booker", session.offering.venue)
    _given_member("wl-queued", session.offering.venue)
    booker = _as_member(base_url, "wl-booker")
    queued = _as_member(base_url, "wl-queued")

    _book(booker, session.pk)
    full = queued.client.post(f"{queued.api}/bookings/", json={"session": session.pk})
    assert full.status_code == 409, full.text
    waiting = _book(queued, session.pk, waitlist=True)
    assert waiting["status"] == "waitlisted"
    assert waiting["credits_spent"] == 0


def test_cancel_promotes_waitlisted_member(base_url):
    session = _given_session("Tiny Spin", starts_in_hours=24, capacity=1)
    _given_member("wl-booker", session.offering.venue)
    _given_member("wl-queued", session.offering.venue)
    booker = _as_member(base_url, "wl-booker")
    queued = _as_member(base_url, "wl-queued")

    booking = _book(booker, session.pk)
    waiting = _book(queued, session.pk, waitlist=True)
    _cancel(booker, booking["id"])

    promoted = _mine(queued, waiting["id"])
    assert promoted["status"] == "booked"
    assert promoted["credits_spent"] > 0


def test_cancel_refunds_and_ledger_balances(base_url):
    session = _given_session("Refund Spin", starts_in_hours=48)
    _given_member("rf-booker", session.offering.venue)
    member = _as_member(base_url, "rf-booker")

    booking = _book(member, session.pk)
    assert booking["credits_spent"] > 0
    record = _cancel(member, booking["id"])
    assert record["credits_refunded"] == booking["credits_spent"]
    assert _mine(member, booking["id"])["status"] == "cancelled"
    refund = _ledger_entry(member, booking["id"], "refund")
    assert refund is not None and refund["delta"] == booking["credits_spent"]


def test_late_cancel_forfeits_credit(base_url):
    from booking.models import CancellationPolicy

    session = _given_session("Late Spin", starts_in_hours=2)
    _given_member("lc-booker", session.offering.venue)
    _given_policy(
        session.offering.venue.organization,
        CancellationPolicy.Enforcement.LOSE_CREDIT,
    )
    member = _as_member(base_url, "lc-booker")

    booking = _book(member, session.pk)
    outcome = _cancel(member, booking["id"])
    assert (
        outcome["was_late"],
        outcome["enforcement_applied"],
        outcome["credits_refunded"],
    ) == (True, "lose_credit", 0)
    assert _mine(member, booking["id"])["status"] == "late_cancelled"
    assert _ledger_entry(member, booking["id"], "refund") is None
