"""Smoke journey against the live app: login → schedule → book →
cancel → refund visible in the ledger → door grants, stranger denied.

One ordered journey (plus an independent door test): smoke must stay
fast and deterministic, never share hidden state between files.
"""

from datetime import timedelta
from uuid import uuid4

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
    listed = member.get(f"{api}/classes/")
    assert listed.status_code == 200
    upcoming = [
        klass
        for klass in listed.json()
        if klass["starts_at"] > (timezone.now() + timedelta(hours=9)).isoformat()
    ]
    assert upcoming, "seed must provide a class outside the cancel window"
    return upcoming


def _try_book(api, member, upcoming):
    for klass in upcoming[:3]:
        attempt = member.post(
            f"{api}/bookings/",
            json={
                "scheduled_class": klass["id"],
                "idempotency_key": f"smoke-1-{uuid4().hex}",
            },
        )
        if attempt.status_code == 201:
            return attempt.json()["id"]
    raise AssertionError("no bookable upcoming class")


def test_login_and_schedule(base_url):
    api = f"{base_url}/api/v1"
    member = _login(base_url, f"{ORG_SLUG}-member")

    assert _upcoming(api, member) != []


def test_calendar_matches_class_list(base_url):
    api = f"{base_url}/api/v1"
    member = _login(base_url, f"{ORG_SLUG}-member")
    start = timezone.now()
    end = start + timedelta(days=7)
    params = {"from": start.isoformat(), "to": end.isoformat()}

    listed = member.get(f"{api}/classes/", params=params)
    assert listed.status_code == 200
    events = member.get(f"{api}/calendar/", params=params)
    assert events.status_code == 200
    class_events = [event for event in events.json() if event["kind"] == "class"]
    assert {event["id"] for event in class_events} == {
        klass["id"] for klass in listed.json()
    }


def test_book_cancel_refund(base_url):
    api = f"{base_url}/api/v1"
    member = _login(base_url, f"{ORG_SLUG}-member")
    booking_id = _try_book(api, member, _upcoming(api, member))

    cancelled = member.post(f"{api}/bookings/{booking_id}/cancel/")
    assert cancelled.status_code == 200

    ledger = member.get(f"{api}/ledger/")
    assert ledger.status_code == 200
    reasons = {entry["reason"] for entry in ledger.json()}
    assert {"purchase", "booking", "refund"} <= reasons


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
