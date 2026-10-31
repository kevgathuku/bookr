from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from test_staff_api import _member, _staff, _venue

from organizations.models import Membership

pytestmark = pytest.mark.django_db

#  Desk seam: what remains after the booking-model swap (.4/.6 own the rest).
#  - roster GET lists a day's venue bookings with member + session info.
#  - member search GET finds venue members by username fragment.
#  - check-in / no-show return with the cancel and desk tickets.


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


def _session(venue):
    from tests.factories import ClassOfferingFactory, ClassSessionFactory

    offering = ClassOfferingFactory(venue=venue, title="Spin")
    return ClassSessionFactory(
        offering=offering, starts_at=timezone.now() + timedelta(days=1)
    )


def _member_with_plan(venue, username):
    from tests.factories import (
        MembershipPlanFactory,
        PlanMembershipFactory,
        UserFactory,
    )

    member = UserFactory(username=username)
    plan = MembershipPlanFactory(organization=venue.organization)
    PlanMembershipFactory(user=member, plan=plan, credits_remaining=5)
    return member


def _book(member, session):
    from booking.services import book_session

    return book_session(member=member, session=session)


class TestRoster:
    def test_roster_rejects_bad_date(self):
        venue = _venue()

        response = _client(_staff(venue)).get(
            "/api/v1/bookings/roster/?date=not-a-date"
        )

        assert response.status_code == 400

    def test_roster_lists_todays_venue_bookings(self):
        venue = _venue()
        session = _session(venue)
        member = _member_with_plan(venue, "roster-member")
        booking = _book(member, session)
        day = (timezone.now() + timedelta(days=1)).date().isoformat()

        response = _client(_staff(venue)).get(f"/api/v1/bookings/roster/?date={day}")

        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert rows[booking.pk]["member"].startswith("roster-member")
        assert rows[booking.pk]["session_title"] == "Spin"


class TestMemberSearch:
    def test_search_finds_venue_member(self):
        venue = _venue()
        _member(venue, "searchable-sam")

        response = _client(_staff(venue)).get("/api/v1/members/search/?q=sam")

        assert response.status_code == 200
        assert any(
            row["username"].startswith("searchable-sam") for row in response.json()
        )
        assert "id" in response.json()[0]

    def test_staff_can_list_member_passes(self):
        venue = _venue()
        member = _member(venue, "pass-holder")

        response = _client(_staff(venue)).get(f"/api/v1/passes/?member={member.pk}")

        assert response.status_code == 200

    def test_search_finds_spanning_member(self):
        venue = _venue()
        spanning = _member(venue, "spanning-sue")
        Membership.objects.filter(user=spanning).update(venue=None)

        response = _client(_staff(venue)).get("/api/v1/members/search/?q=sue")

        assert response.status_code == 200
        assert any(
            row["username"].startswith("spanning-sue") for row in response.json()
        )

    def test_member_cannot_search(self):
        venue = _venue()

        response = _client(_member(venue)).get("/api/v1/members/search/?q=a")

        assert response.status_code in (403, 404)
