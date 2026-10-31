from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from booking.services import book_session
from organizations.models import Membership, Organization, Venue
from scheduling.models import ClassType, Room, ScheduledClass
from tests.factories import (
    ClassOfferingFactory,
    ClassSessionFactory,
    MembershipPlanFactory,
    OrgRoleFactory,
    PlanMembershipFactory,
    UserFactory,
    VenueFactory,
)

#  Schedule API seam: GET /api/v1/classes/ is bounded (31d max), cheap
#  (memberships + org-roles loads; contract drops the legacy load), and
#  venue-scoped. Publishing is staff-only.
#
#  Isolation trio: cross-organization access 404s, cross-venue access 404s
#  (no id leaks — never 403), and a spanning member gets 200 in both venues.


def _user(username, password="password"):
    user = get_user_model().objects.create_user(username=username)
    user.set_password(password)
    user.save()
    return user


@pytest.fixture
def world(db):
    """Two orgs: A spanning with two venues, B per-venue with one venue."""
    org_a = Organization.objects.create(slug="org-a", name="A")
    a1 = Venue.objects.create(organization=org_a, slug="main", name="Main")
    a2 = Venue.objects.create(organization=org_a, slug="annex", name="Annex")
    org_b = Organization.objects.create(
        slug="org-b", name="B", membership_scope=Organization.Scope.PER_VENUE
    )
    b1 = Venue.objects.create(organization=org_b, slug="box", name="Box")
    teacher = _user("teacher")
    for venue in (a1, a2, b1):
        ct = ClassType.objects.create(
            venue=venue, name="Spin", duration_min=45, capacity_default=20
        )
        room = Room.objects.create(venue=venue, name="Studio", capacity=20)
        start = timezone.now() + timedelta(days=1)
        ScheduledClass.objects.create(
            venue=venue,
            class_type=ct,
            room=room,
            teacher=teacher,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
        )
    spanning = _user("spanning")
    Membership.objects.create(
        organization=org_a, venue=None, user=spanning, role=Membership.Role.MEMBER
    )
    pinned = _user("pinned")
    Membership.objects.create(
        organization=org_b, venue=b1, user=pinned, role=Membership.Role.MEMBER
    )
    return {
        "org_a": org_a,
        "a1": a1,
        "a2": a2,
        "b1": b1,
        "teacher": teacher,
        "spanning": spanning,
        "pinned": pinned,
    }


def _client(user, venue_slug=None):
    client = APIClient()
    client.force_authenticate(user=user)
    if venue_slug:
        client.defaults["HTTP_X_VENUE_SLUG"] = venue_slug
    return client


class TestScheduleList:
    def test_bounded_list_query_count(self, world):
        client = _client(world["spanning"], "main")

        with CaptureQueriesContext(connection) as ctx:
            response = client.get("/api/v1/classes/")

        assert len(ctx) == 4  # memberships + org-roles loads (contract: 3)

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["venue"] == world["a1"].pk

    def test_window_over_31d_rejected(self, world):
        client = _client(world["spanning"], "main")
        now = timezone.now()

        response = client.get(
            "/api/v1/classes/",
            {
                "from": now.isoformat(),
                "to": (now + timedelta(days=32)).isoformat(),
            },
        )

        assert response.status_code == 400

    def test_unauthenticated_denied(self, world):
        response = Client().get("/api/v1/classes/", HTTP_X_VENUE_SLUG="main")

        assert response.status_code in (401, 403, 404)


class TestIsolation:
    def test_cross_org_404(self, world):
        # Pinned B1 member asks for an A venue: 404, not 403 (no id leak).
        client = _client(world["pinned"], "main")

        assert client.get("/api/v1/classes/").status_code == 404

    def test_cross_venue_404(self, world):
        # Member of a second B venue asks for the first: 404, not 403.
        other = Venue.objects.create(
            organization=world["b1"].organization, slug="other", name="Other"
        )
        outsider = _user("outsider-b2")
        Membership.objects.create(
            organization=other.organization,
            venue=other,
            user=outsider,
            role=Membership.Role.MEMBER,
        )

        assert _client(outsider, "box").get("/api/v1/classes/").status_code == 404

    def test_spanning_member_200_both_venues(self, world):
        assert (
            _client(world["spanning"], "main").get("/api/v1/classes/").status_code
            == 200
        )
        assert (
            _client(world["spanning"], "annex").get("/api/v1/classes/").status_code
            == 200
        )


class TestAuth:
    def test_jwt_obtain(self, world):
        client = APIClient()

        response = client.post(
            "/api/v1/auth/token/",
            {"username": "spanning", "password": "password"},
        )

        assert response.status_code == 200
        assert "access" in response.data


class TestPublish:
    def _payload(self, world, venue):
        klass = ScheduledClass.objects.filter(venue=venue).first()
        start = timezone.now() + timedelta(days=2)
        return {
            "venue": venue.pk,
            "class_type": klass.class_type_id,
            "room": klass.room_id,
            "teacher": klass.teacher_id,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
        }

    def test_member_cannot_publish(self, world):
        client = _client(world["spanning"], "main")

        response = client.post("/api/v1/classes/", self._payload(world, world["a1"]))

        assert response.status_code == 403

    def test_staff_can_publish(self, world):
        staff = _user("manager")
        Membership.objects.create(
            organization=world["org_a"],
            venue=world["a1"],
            user=staff,
            role=Membership.Role.MANAGER,
        )
        client = _client(staff, "main")

        response = client.post("/api/v1/classes/", self._payload(world, world["a1"]))

        assert response.status_code == 201

    def test_overlapping_publish_refused(self, world):
        staff = _user("manager")
        Membership.objects.create(
            organization=world["org_a"],
            venue=world["a1"],
            user=staff,
            role=Membership.Role.MANAGER,
        )
        client = _client(staff, "main")
        existing = ScheduledClass.objects.filter(venue=world["a1"]).first()

        response = client.post(
            "/api/v1/classes/",
            {
                "venue": world["a1"].pk,
                "class_type": existing.class_type_id,
                "room": existing.room_id,
                "teacher": existing.teacher_id,
                "starts_at": existing.starts_at.isoformat(),
                "ends_at": existing.ends_at.isoformat(),
            },
        )

        assert response.status_code == 400


pytestmark = pytest.mark.django_db


class TestSessionList:
    """New-graph schedule reads: offerings + sessions, derived ends."""

    def _world(self):
        from organizations.models import OrgRole

        venue = VenueFactory()
        teacher = _user("sched-teacher")
        offering = ClassOfferingFactory(venue=venue, teacher=teacher, title="Spin")
        member = _user("sched-member")
        OrgRoleFactory(
            organization=venue.organization,
            venue=venue,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        return venue, offering, member

    def _get(self, user, venue, params=None):
        return _client(user, venue.slug).get("/api/v1/sessions/", params or {})

    def test_lists_window_with_derived_ends(self):
        venue, offering, member = self._world()
        session = ClassSessionFactory(offering=offering)
        start = session.starts_at.isoformat()
        end = (session.starts_at + timedelta(days=1)).isoformat()

        params = {"from": start, "to": end}
        response = self._get(member, venue, params)

        assert response.status_code == 200
        assert len(response.data) == 1
        row = response.data[0]
        assert row["offering"] == offering.pk
        from django.utils.dateparse import parse_datetime

        assert parse_datetime(row["ends_at"]) == session.ends_at

    def test_excludes_cancelled(self):
        from django.utils import timezone as tz

        venue, offering, member = self._world()
        session = ClassSessionFactory(offering=offering)
        session.cancelled_at = tz.now()
        session.save(update_fields=["cancelled_at"])
        start = session.starts_at.isoformat()
        end = (session.starts_at + timedelta(days=1)).isoformat()

        params = {"from": start, "to": end}
        response = self._get(member, venue, params)

        assert response.status_code == 200
        assert not response.data

    def test_window_over_31d_rejected(self):
        venue, _offering, member = self._world()
        start = timezone.now()
        end = start + timedelta(days=32)

        params = {"from": start.isoformat(), "to": end.isoformat()}
        response = self._get(member, venue, params)

        assert response.status_code == 400

    def test_lists_spots_left(self):
        venue, offering, member = self._world()
        session = ClassSessionFactory(offering=offering)
        booker = UserFactory(username="spot-booker")
        plan = MembershipPlanFactory(organization=venue.organization)
        membership = PlanMembershipFactory(user=booker, plan=plan, credits_remaining=5)
        book_session(member=booker, session=session, membership=membership)
        start = session.starts_at.isoformat()
        end = (session.starts_at + timedelta(days=1)).isoformat()
        params = {"from": start, "to": end}

        response = self._get(member, venue, params)

        assert response.status_code == 200
        row = next(r for r in response.data if r["id"] == session.pk)
        assert row["spots_left"] == session.capacity - 1

    def test_cross_venue_404(self):
        venue, _offering, member = self._world()
        other = VenueFactory(organization=venue.organization)

        response = self._get(member, other)

        assert response.status_code == 404


class TestOfferingList:
    def test_lists_venue_offerings(self):
        from organizations.models import OrgRole

        venue = VenueFactory()
        ClassOfferingFactory(venue=venue, title="Spin")
        member = _user("offering-member")
        OrgRoleFactory(
            organization=venue.organization,
            venue=venue,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        client = _client(member, venue.slug)

        response = client.get("/api/v1/offerings/")

        assert response.status_code == 200
        assert [row["title"] for row in response.data] == ["Spin"]


class TestGenerateSessionsEndpoint:
    def _client(self, user, venue):
        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_VENUE_SLUG"] = venue.slug
        return client

    def _desk(self, venue):
        from organizations.models import OrgRole

        user = UserFactory(username="desk-gen")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=user,
            role=OrgRole.Role.FRONTDESK,
        )
        return user

    def _payload(self, start):
        return {
            "rrule": start.strftime("DTSTART:%Y%m%dT%H%M%S\n")
            + "RRULE:FREQ=WEEKLY;COUNT=2",
            "after": (start - timedelta(hours=1)).isoformat(),
            "before": (start + timedelta(days=30)).isoformat(),
        }

    def test_desk_generates_series(self):
        venue = VenueFactory(slug="series")
        offering = ClassOfferingFactory(venue=venue, duration_minutes=60)
        start = timezone.now() + timedelta(days=1)

        response = self._client(self._desk(venue), venue).post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/",
            self._payload(start),
            format="json",
        )

        assert response.status_code == 201
        assert len(response.data) == 2

    def test_member_cannot_generate(self):
        from organizations.models import OrgRole

        venue = VenueFactory(slug="series-member")
        offering = ClassOfferingFactory(venue=venue, duration_minutes=60)
        member = UserFactory(username="member-gen")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        start = timezone.now() + timedelta(days=1)

        response = self._client(member, venue).post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/",
            self._payload(start),
            format="json",
        )

        assert response.status_code == 403

    def test_bad_rule_is_400(self):
        venue = VenueFactory(slug="series-bad")
        offering = ClassOfferingFactory(venue=venue, duration_minutes=60)
        start = timezone.now() + timedelta(days=1)
        payload = self._payload(start)
        payload["rrule"] = "not a rule"

        response = self._client(self._desk(venue), venue).post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/",
            payload,
            format="json",
        )

        assert response.status_code == 400
