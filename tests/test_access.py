from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.utils import timezone
from rest_framework.test import APIClient

from access.models import AccessEvent, AccessPoint
from booking.services import book_seat
from organizations.models import Membership, Organization, Venue, VenuePolicy
from passes.models import PassProduct
from passes.services import issue_pass
from scheduling.models import ClassType, Room, ScheduledClass

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


#  Door check seam: POST /api/access/check with per-controller token.
#  - Grant iff active pass OR live booking window OR staff; else deny.
#  - Every identified attempt logs an AccessEvent with reason...
#  - ...except 60s passback replays, which return the prior decision rowless.
#  - DB outage denies (fail-closed drill) — cache is latency only.
#  - door_grants_total increments per grant; frontdesk reads recent events.


def _user(username):
    return get_user_model().objects.create_user(username=username)


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    venue = Venue.objects.create(organization=org, slug=slug, name=slug.title())
    VenuePolicy.objects.create(venue=venue)
    return venue


def _point(venue):
    point = AccessPoint.objects.create(
        venue=venue, name="Front Door", controller_id="door-1"
    )
    token = point.set_token()
    point.save()
    return point, token


def _member_with_pass(venue, username="member"):
    member = _user(username)
    Membership.objects.create(
        organization=venue.organization,
        venue=venue,
        user=member,
        role=Membership.Role.MEMBER,
    )
    product = PassProduct.objects.create(
        venue=venue, name="Pack", credits_total=5, validity_days=30
    )
    issue_pass(member, product)
    return member


def _class(venue, teacher, start):
    class_type, _ = ClassType.objects.get_or_create(
        venue=venue, name="Spin", defaults={"duration_min": 45}
    )
    room, _ = Room.objects.get_or_create(
        venue=venue, name="Studio", defaults={"capacity": 20}
    )
    return ScheduledClass.objects.create(
        venue=venue,
        class_type=class_type,
        room=room,
        teacher=teacher,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


def _check(token, member_pk, point_pk):
    client = APIClient()
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {token}"
    return client.post(
        "/api/access/check/",
        {"access_point": point_pk, "member": member_pk},
        format="json",
    )


class TestGrantDeny:
    def test_active_pass_grants_and_logs(self):
        venue = _venue()
        point, token = _point(venue)
        member = _member_with_pass(venue)

        response = _check(token, member.pk, point.pk)

        assert response.status_code == 200
        assert response.data["granted"] is True
        event = AccessEvent.objects.get(access_point=point, member=member)
        assert (event.granted, event.reason) == (True, "active_pass")

    def test_live_booking_window_grants(self):
        venue = _venue()
        point, token = _point(venue)
        teacher = _user("teacher")
        member = _user("dropin")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=member,
            role=Membership.Role.MEMBER,
        )
        start = timezone.now() - timedelta(minutes=5)  # class started 5m ago
        klass = _class(venue, teacher, start)
        # No pass: book via unlimited? booking needs credit — grant one credit.
        product = PassProduct.objects.create(
            venue=venue, name="Single", credits_total=1, validity_days=30
        )
        issue_pass(member, product)
        book_seat(member, klass, idempotency_key="dropin-1")

        response = _check(token, member.pk, point.pk)

        assert response.data["granted"] is True
        assert AccessEvent.objects.get(member=member).reason == "live_booking"

    def test_staff_grants_without_pass_or_booking(self):
        venue = _venue()
        point, token = _point(venue)
        staff = _user("manager")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=staff,
            role=Membership.Role.MANAGER,
        )

        response = _check(token, staff.pk, point.pk)

        assert response.data["granted"] is True
        assert AccessEvent.objects.get(member=staff).reason == "staff"

    def test_stranger_denies_and_logs(self):
        venue = _venue()
        point, token = _point(venue)
        stranger = _user("stranger")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=stranger,
            role=Membership.Role.MEMBER,
        )

        response = _check(token, stranger.pk, point.pk)

        assert response.data["granted"] is False
        assert AccessEvent.objects.get(member=stranger).reason == "no_access"

    def test_bad_token_401(self):
        venue = _venue()
        point, _ = _point(venue)
        member = _member_with_pass(venue)

        response = _check("wrong-token", member.pk, point.pk)

        assert response.status_code == 401

    def test_metric_counts_grants(self):
        from django.test import Client

        venue = _venue()
        point, token = _point(venue)
        member = _member_with_pass(venue)
        before = Client().get("/metrics/").content.decode().count("door_grants_total")

        _check(token, member.pk, point.pk)

        after = Client().get("/metrics/").content.decode().count("door_grants_total")
        assert after > before


class TestPassback:
    def test_replay_within_60s_returns_prior_without_new_event(self):
        venue = _venue()
        point, token = _point(venue)
        member = _member_with_pass(venue)

        first = _check(token, member.pk, point.pk)
        second = _check(token, member.pk, point.pk)

        assert (first.data["granted"], second.data["granted"]) == (True, True)
        assert second.data["reason"] == "passback_replay"
        assert AccessEvent.objects.filter(member=member).count() == 1


class TestFailClosed:
    def test_db_outage_denies(self):
        venue = _venue()
        point, token = _point(venue)
        member = _member_with_pass(venue)

        with mock.patch("access.views.decide", side_effect=OperationalError("db gone")):
            response = _check(token, member.pk, point.pk)

        assert response.status_code == 200
        assert response.data["granted"] is False


class TestRecentEvents:
    def test_frontdesk_reads_member_cannot(self):
        venue = _venue()
        point, token = _point(venue)
        member = _member_with_pass(venue)
        staff = _user("frontdesk")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=staff,
            role=Membership.Role.FRONTDESK,
        )
        _check(token, member.pk, point.pk)

        client = APIClient()
        client.force_authenticate(user=staff)
        client.defaults["HTTP_X_VENUE_SLUG"] = "downtown"
        staff_view = client.get("/api/v1/access/events/")
        client.force_authenticate(user=member)
        member_view = client.get("/api/v1/access/events/")

        assert staff_view.status_code == 200
        assert len(staff_view.data) == 1
        assert member_view.status_code == 403

    def test_latency_budget(self):
        import time

        venue = _venue()
        point, token = _point(venue)
        member = _member_with_pass(venue)
        _check(token, member.pk, point.pk)  # warm cache
        elapsed = []
        for _ in range(20):
            started = time.perf_counter()
            _check(token, member.pk, point.pk)
            elapsed.append(time.perf_counter() - started)
        elapsed.sort()

        assert elapsed[18] < 1  # p95 proxy; seed-scale must stay far under
