"""Smoke journey against the live app: login → schedule → book →
ledger shows the spend → door grants, stranger denied.

Cancel + refund return with the cancel ticket (.4); until then this file
asserts the book half only (status, debit, list).

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
