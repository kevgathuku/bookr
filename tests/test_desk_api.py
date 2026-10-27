from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from test_staff_api import _class, _member, _staff, _venue

from booking.models import Booking
from organizations.models import Membership

pytestmark = pytest.mark.django_db

#  Desk seam: the three endpoints /desk needs that no ticket has named yet.
#  - checkin POST stamps a confirmed booking (staff only, venue-scoped).
#  - roster GET lists a day's venue bookings with member + class info.
#  - member search GET finds venue members by username fragment.


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


def _book(member, klass):
    return Booking.objects.create(
        member=member,
        venue=klass.venue,
        scheduled_class=klass,
        status=Booking.Status.CONFIRMED,
        idempotency_key=f"desk-{member.pk}-{klass.pk}",
    )


class TestCheckin:
    def test_staff_checkin_stamps_confirmed(self):
        venue = _venue()
        booking = _book(_member(venue), _class(venue))

        response = _client(_staff(venue)).post(
            f"/api/v1/bookings/{booking.pk}/checkin/"
        )

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.checked_in_at is not None

    def test_member_cannot_checkin(self):
        venue = _venue()
        booking = _book(_member(venue), _class(venue))

        response = _client(_member(venue, "other")).post(
            f"/api/v1/bookings/{booking.pk}/checkin/"
        )

        assert response.status_code in (403, 404)


class TestRoster:
    def test_roster_rejects_bad_date(self):
        venue = _venue()

        response = _client(_staff(venue)).get(
            "/api/v1/bookings/roster/?date=not-a-date"
        )

        assert response.status_code == 400

    def test_roster_lists_todays_venue_bookings(self):
        venue = _venue()
        klass = _class(venue)
        member = _member(venue, "roster-member")
        booking = _book(member, klass)
        day = (timezone.now() + timedelta(days=1)).date().isoformat()

        response = _client(_staff(venue)).get(f"/api/v1/bookings/roster/?date={day}")

        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert rows[booking.pk]["member"].startswith("roster-member")
        assert rows[booking.pk]["class_title"] == "Spin"


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
