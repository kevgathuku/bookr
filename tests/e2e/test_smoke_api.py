"""Smoke journey against the live app: login → schedule → book →
ledger shows the spend → cancel refunds (or forfeits when late) →
door grants, stranger denied.

One ordered journey (plus an independent door test): smoke must stay
fast and deterministic, never share hidden state between files.
"""

from datetime import timedelta

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
    session.base = base_url
    return session


def _login(base_url, username):
    anonymous = _session(base_url, venue=False)
    response = anonymous.post(
        f"{base_url}/api/v1/auth/token/",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return _session(base_url, token=response.json()["access"])


def _upcoming(api, member):
    start = timezone.now()
    end = start + timedelta(days=7)
    listed = member.get(
        f"{api}/sessions/",
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


def _try_book(api, member, upcoming):
    for session in upcoming[:3]:
        attempt = member.post(f"{api}/bookings/", json={"session": session["id"]})
        if attempt.status_code == 201:
            return attempt.json()["id"]
    raise AssertionError("no bookable upcoming session")


def test_login_and_schedule(base_url):
    api = f"{base_url}/api/v1"
    member = _login(base_url, f"{ORG_SLUG}-member")

    assert _upcoming(api, member) != []


def test_calendar_matches_session_list(base_url):
    api = f"{base_url}/api/v1"
    member = _login(base_url, f"{ORG_SLUG}-member")
    start = timezone.now()
    end = start + timedelta(days=7)
    params = {"from": start.isoformat(), "to": end.isoformat()}

    listed = member.get(f"{api}/sessions/", params=params)
    assert listed.status_code == 200
    events = member.get(f"{api}/calendar/", params=params)
    assert events.status_code == 200
    session_events = [event for event in events.json() if event["kind"] == "session"]
    assert {event["id"] for event in session_events} == {
        session["id"] for session in listed.json()
    }


def test_book_debits_and_lists(base_url):
    # Cancel + refund return with the cancel ticket; this asserts the book half.
    api = f"{base_url}/api/v1"
    member = _login(base_url, f"{ORG_SLUG}-member")
    booking_id = _try_book(api, member, _upcoming(api, member))

    mine = member.get(f"{api}/bookings/me/", params={"mine": "true"})
    assert mine.status_code == 200
    booked = next(b for b in mine.json() if b["id"] == booking_id)
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

    granted = door.post(
        f"{base_url}/api/access/check/",
        json={"access_point": point.pk, "member": member_id},
    )
    denied = door.post(
        f"{base_url}/api/access/check/",
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


def _waitlist_world():
    """Committed capacity-1 GROUP session + two credited members."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from organizations.management.seed_helpers import booker_membership, ensure_org_role
    from organizations.models import OrgRole, Venue
    from tests.factories import ClassOfferingFactory, ClassSessionFactory

    users = get_user_model().objects
    venue = Venue.objects.get(organization__slug=ORG_SLUG, slug="main")
    teacher = users.get(username="e2e-run-teacher")
    offering = ClassOfferingFactory(venue=venue, teacher=teacher, title="Tiny Spin")
    session = ClassSessionFactory(
        offering=offering,
        starts_at=timezone.now() + timedelta(days=1),
        capacity=1,
    )
    for username in ("wl-booker", "wl-queued"):
        user = users.create_user(username=username, password=PASSWORD)
        ensure_org_role(venue.organization, user, OrgRole.Role.MEMBER)
        booker_membership(venue, user)
    return session


def test_waitlist_queue_returns_waitlisted(base_url):
    api = f"{base_url}/api/v1"
    session = _waitlist_world()
    booker = _login(base_url, "wl-booker")
    queued = _login(base_url, "wl-queued")

    booked = booker.post(f"{api}/bookings/", json={"session": session.pk})
    assert booked.status_code == 201, booked.text
    full = queued.post(f"{api}/bookings/", json={"session": session.pk})
    assert full.status_code == 409, full.text

    waitlist_url = f"{api}/bookings/?waitlist=true"
    waiting = queued.post(waitlist_url, json={"session": session.pk})
    assert waiting.status_code == 201, waiting.text
    assert waiting.json()["status"] == "waitlisted"
    assert waiting.json()["credits_spent"] == 0


def test_cancel_promotes_waitlisted_member(base_url):
    api = f"{base_url}/api/v1"
    session = _waitlist_world()
    booker = _login(base_url, "wl-booker")
    queued = _login(base_url, "wl-queued")

    booked = booker.post(f"{api}/bookings/", json={"session": session.pk})
    waitlist_url = f"{api}/bookings/?waitlist=true"
    waiting = queued.post(waitlist_url, json={"session": session.pk})
    booking_id = booked.json()["id"]
    cancel = booker.post(f"{api}/bookings/{booking_id}/cancel/", json={})
    assert cancel.status_code == 200, cancel.text

    mine = queued.get(f"{api}/bookings/me/", params={"mine": "true"})
    assert mine.status_code == 200, mine.text
    promoted = next(b for b in mine.json() if b["id"] == waiting.json()["id"])
    assert promoted["status"] == "booked"
    assert promoted["credits_spent"] > 0


def _solo_world(title, username, starts_in_hours, enforcement=None):
    """Committed session + one credited member; optional org-wide policy."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from booking.models import CancellationPolicy
    from organizations.management.seed_helpers import (
        booker_membership,
        ensure_org_role,
    )
    from organizations.models import OrgRole, Venue
    from tests.factories import ClassOfferingFactory, ClassSessionFactory

    users = get_user_model().objects
    venue = Venue.objects.get(organization__slug=ORG_SLUG, slug="main")
    teacher = users.get(username="e2e-run-teacher")
    offering = ClassOfferingFactory(venue=venue, teacher=teacher, title=title)
    session = ClassSessionFactory(
        offering=offering,
        starts_at=timezone.now() + timedelta(hours=starts_in_hours),
    )
    if enforcement is not None:
        CancellationPolicy.objects.create(
            organization=venue.organization,
            enforcement=enforcement,
            late_cancel_hours=12,
        )
    user = users.create_user(username=username, password=PASSWORD)
    ensure_org_role(venue.organization, user, OrgRole.Role.MEMBER)
    booker_membership(venue, user)
    return session


def _ledger_entry(member, api, booking_id, reason):
    ledger = member.get(f"{api}/ledger/")
    assert ledger.status_code == 200, ledger.text
    return next(
        (
            entry
            for entry in ledger.json()
            if entry["booking"] == booking_id and entry["reason"] == reason
        ),
        None,
    )


def test_cancel_refunds_and_ledger_balances(base_url):
    api = f"{base_url}/api/v1"
    session = _solo_world("Refund Spin", "rf-booker", starts_in_hours=48)
    member = _login(base_url, "rf-booker")

    booked = member.post(f"{api}/bookings/", json={"session": session.pk})
    assert booked.status_code == 201, booked.text
    booking_id = booked.json()["id"]
    spent = booked.json()["credits_spent"]
    assert spent > 0

    cancel = member.post(f"{api}/bookings/{booking_id}/cancel/", json={})
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["credits_refunded"] == spent

    mine = member.get(f"{api}/bookings/me/", params={"mine": "true"})
    cancelled = next(b for b in mine.json() if b["id"] == booking_id)
    assert cancelled["status"] == "cancelled"
    refund = _ledger_entry(member, api, booking_id, "refund")
    assert refund is not None and refund["delta"] == spent


def test_late_cancel_forfeits_credit(base_url):
    from booking.models import CancellationPolicy

    api = f"{base_url}/api/v1"
    session = _solo_world(
        "Late Spin",
        "lc-booker",
        starts_in_hours=2,
        enforcement=CancellationPolicy.Enforcement.LOSE_CREDIT,
    )
    member = _login(base_url, "lc-booker")

    booked = member.post(f"{api}/bookings/", json={"session": session.pk})
    assert booked.status_code == 201, booked.text
    booking_id = booked.json()["id"]

    cancel = member.post(f"{api}/bookings/{booking_id}/cancel/", json={})
    assert cancel.status_code == 200, cancel.text
    outcome = cancel.json()
    assert (
        outcome["was_late"],
        outcome["enforcement_applied"],
        outcome["credits_refunded"],
    ) == (True, "lose_credit", 0)

    mine = member.get(f"{api}/bookings/me/", params={"mine": "true"})
    late = next(b for b in mine.json() if b["id"] == booking_id)
    assert late["status"] == "late_cancelled"
    assert _ledger_entry(member, api, booking_id, "refund") is None
