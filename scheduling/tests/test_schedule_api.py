from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from booking.services import book_session
from tests.factories import (
    ClassOfferingFactory,
    ClassSessionFactory,
    OrgRoleFactory,
    PlanFactory,
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


def _make_client(user, venue_slug=None):
    client = APIClient()
    client.force_authenticate(user=user)
    if venue_slug:
        client.defaults["HTTP_X_VENUE_SLUG"] = venue_slug
    return client


@pytest.fixture()
def api_client():
    """Client builder; venues and users vary per call, so the fixture
    returns the maker instead of a single client."""
    return _make_client


@pytest.fixture()
def org():
    from tests.factories import OrganizationFactory

    return OrganizationFactory()


@pytest.fixture()
def venue():
    return VenueFactory()


@pytest.fixture()
def member(venue):
    """Venue-pinned member; the standard world most schedule tests share."""
    from organizations.models import OrgRole

    user = UserFactory()
    OrgRoleFactory(
        organization=venue.organization,
        venue=venue,
        user=user,
        role=OrgRole.Role.MEMBER,
    )
    return user


@pytest.fixture()
def offering(venue):
    return ClassOfferingFactory(venue=venue, title="Spin")


@pytest.fixture()
def member_client(member, venue):
    return _make_client(member, venue.slug)


class TestIsolation:
    def test_cross_venue_404(self, org, api_client):
        from organizations.models import OrgRole
        from tests.factories import OrgRoleFactory, VenueFactory

        VenueFactory(organization=org, slug="first")
        second = VenueFactory(organization=org, slug="second")
        user = UserFactory(username="outsider")
        OrgRoleFactory(
            organization=org, venue=second, user=user, role=OrgRole.Role.MEMBER
        )

        assert api_client(user, "first").get("/api/v1/sessions/").status_code == 404

    def test_spanning_member_200_both_venues(self, org, api_client):
        from organizations.models import OrgRole
        from tests.factories import OrgRoleFactory, VenueFactory

        VenueFactory(organization=org, slug="first")
        VenueFactory(organization=org, slug="second")
        user = UserFactory(username="spanning")
        OrgRoleFactory(
            organization=org, venue=None, user=user, role=OrgRole.Role.MEMBER
        )

        assert api_client(user, "first").get("/api/v1/sessions/").status_code == 200
        assert api_client(user, "second").get("/api/v1/sessions/").status_code == 200


class TestGeneratePermissions:
    def test_member_cannot_generate(self, member_client, offering):
        response = member_client.post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/", {}
        )

        assert response.status_code == 403


class TestAuth:
    def test_jwt_obtain(self):
        UserFactory(username="jwt-user")
        client = APIClient()

        response = client.post(
            "/api/v1/auth/token/",
            {"username": "jwt-user", "password": "password"},
        )

        assert response.status_code == 200
        assert "access" in response.data


pytestmark = pytest.mark.django_db


class TestSessionList:
    """New-graph schedule reads: offerings + sessions, derived ends."""

    def _get(self, client, params=None):
        return client.get("/api/v1/sessions/", params or {})

    def test_lists_window_with_derived_ends(self, member_client, offering):
        session = ClassSessionFactory(offering=offering)
        start = session.starts_at.isoformat()
        end = (session.starts_at + timedelta(days=1)).isoformat()

        params = {"from": start, "to": end}
        response = self._get(member_client, params)

        assert response.status_code == 200
        assert len(response.data) == 1
        row = response.data[0]
        assert row["offering"] == offering.pk
        from django.utils.dateparse import parse_datetime

        assert parse_datetime(row["ends_at"]) == session.ends_at

    def test_excludes_cancelled(self, member_client, offering):
        from django.utils import timezone as tz

        session = ClassSessionFactory(offering=offering)
        session.cancelled_at = tz.now()
        session.save(update_fields=["cancelled_at"])
        start = session.starts_at.isoformat()
        end = (session.starts_at + timedelta(days=1)).isoformat()

        params = {"from": start, "to": end}
        response = self._get(member_client, params)

        assert response.status_code == 200
        assert not response.data

    def test_window_over_31d_rejected(self, member_client):
        start = timezone.now()
        end = start + timedelta(days=32)

        params = {"from": start.isoformat(), "to": end.isoformat()}
        response = self._get(member_client, params)

        assert response.status_code == 400

    def test_lists_spots_left(self, member_client, venue, offering):
        session = ClassSessionFactory(offering=offering)
        booker = UserFactory(username="spot-booker")
        plan = PlanFactory(organization=venue.organization)
        membership = PlanMembershipFactory(user=booker, plan=plan, credits_remaining=5)
        book_session(member=booker, session=session, membership=membership)
        start = session.starts_at.isoformat()
        end = (session.starts_at + timedelta(days=1)).isoformat()
        params = {"from": start, "to": end}

        response = self._get(member_client, params)

        assert response.status_code == 200
        row = next(r for r in response.data if r["id"] == session.pk)
        assert row["spots_left"] == session.capacity - 1

    def test_cross_venue_404(self, api_client, member, venue):
        other = VenueFactory(organization=venue.organization)

        response = api_client(member, other.slug).get("/api/v1/sessions/")

        assert response.status_code == 404


class TestOfferingList:
    def test_lists_venue_offerings(self, member_client, offering):
        response = member_client.get("/api/v1/offerings/")

        assert response.status_code == 200
        assert [row["title"] for row in response.data] == ["Spin"]


class TestGenerateSessionsEndpoint:
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

    def test_desk_generates_series(self, api_client):
        venue = VenueFactory(slug="series")
        offering = ClassOfferingFactory(venue=venue, duration_minutes=60)
        start = timezone.now() + timedelta(days=1)

        response = api_client(self._desk(venue), venue.slug).post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/",
            self._payload(start),
            format="json",
        )

        assert response.status_code == 201
        assert len(response.data) == 2

    def test_member_cannot_generate(self, api_client):
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

        response = api_client(member, venue.slug).post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/",
            self._payload(start),
            format="json",
        )

        assert response.status_code == 403

    def test_bad_rule_is_400(self, api_client):
        venue = VenueFactory(slug="series-bad")
        offering = ClassOfferingFactory(venue=venue, duration_minutes=60)
        start = timezone.now() + timedelta(days=1)
        payload = self._payload(start)
        payload["rrule"] = "not a rule"

        response = api_client(self._desk(venue), venue.slug).post(
            f"/api/v1/offerings/{offering.pk}/sessions/generate/",
            payload,
            format="json",
        )

        assert response.status_code == 400


class TestPolicyListEndpoint:
    def _setup(self, slug="policies"):
        from organizations.models import OrgRole

        venue = VenueFactory(slug=slug)
        staff = UserFactory(username=f"staff-{slug}")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=staff,
            role=OrgRole.Role.MANAGER,
        )
        member = UserFactory(username=f"member-{slug}")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        return venue, staff, member

    def test_staff_filters_by_category(self, api_client):
        from booking.models import CancellationPolicy

        venue, staff, _member = self._setup()
        org = venue.organization
        CancellationPolicy.objects.create(
            organization=org,
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.STRIKE,
        )
        CancellationPolicy.objects.create(
            organization=org,
            class_category="private",
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.LOSE_CREDIT,
        )

        response = api_client(staff, venue.slug).get(
            "/api/v1/cancellation-policies/?class_category=private"
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["class_category"] == "private"

    def test_member_cannot_list_policies(self, api_client):
        venue, _staff, member = self._setup(slug="policies-member")

        response = api_client(member, venue.slug).get("/api/v1/cancellation-policies/")

        assert response.status_code == 403

    def test_session_list_filters_by_category(self, api_client):
        venue = VenueFactory(slug="series-filter")
        group = ClassOfferingFactory(venue=venue, category="group", duration_minutes=60)
        private = ClassOfferingFactory(
            venue=venue, category="private", duration_minutes=60
        )
        start = timezone.now() + timedelta(days=1)
        ClassSessionFactory(offering=group, starts_at=start)
        ClassSessionFactory(offering=private, starts_at=start)
        member = UserFactory(username="filter-member")
        from organizations.models import OrgRole

        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )

        response = api_client(member, venue.slug).get(
            "/api/v1/sessions/?offering__category=private"
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["category"] == "private"
