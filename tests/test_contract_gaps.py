from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import Membership, Organization, Venue, VenuePolicy

pytestmark = pytest.mark.django_db

#  Frontend-contract gaps: what SPEC-frontend §2 calls that the backend
#  doesn't serve yet. All small, all asserted before implementation.
#  - GET /me (user + memberships for the venue switcher).
#  - GET /policy (current windows for "free cancel until" display).
#  - POST /bookings?waitlist=true (contract spelling of the waitlist offer).
#  - GET /bookings?mine=true (contract spelling of the own list).
#  - GET /classes?venue= must agree with the venue header (else 404).
#  - Slots accept a from/to range (appointment UI), duration defaults.
#  - Calendar accepts ?room alongside ?resource.


def _user(username):
    return get_user_model().objects.create_user(username=username)


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    venue = Venue.objects.create(organization=org, slug=slug, name=slug.title())
    VenuePolicy.objects.create(venue=venue)
    return venue


def _member(venue, username="member"):
    user = _user(username)
    Membership.objects.create(
        organization=venue.organization,
        venue=venue,
        user=user,
        role=Membership.Role.MEMBER,
    )
    return user


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


class TestMe:
    def test_me_returns_user_and_memberships(self):
        venue = _venue()
        user = _member(venue)

        response = _client(user).get("/api/v1/me/")

        assert response.status_code == 200
        assert response.data["username"] == user.username
        assert response.data["memberships"][0]["role"] == "member"
        assert response.data["memberships"][0]["venue"] == venue.slug

    def test_me_includes_identity_and_venue_time_zone(self):
        venue = _venue()
        user = _member(venue)

        response = _client(user).get("/api/v1/me/")

        assert response.status_code == 200
        assert response.data["id"] == user.pk
        assert response.data["venues"][0]["time_zone"] == venue.time_zone


class TestPolicyCurrent:
    def test_current_policy(self):
        venue = _venue()

        response = _client(_member(venue)).get("/api/v1/policy/")

        assert response.status_code == 200
        assert response.data["class_late_cancel_hours"] == 8


class TestBookingSpellings:
    def _full_class(self, venue):
        from scheduling.models import ClassType, Room, ScheduledClass

        start = timezone.now() + timedelta(days=1)
        class_type, _ = ClassType.objects.get_or_create(
            venue=venue, name="Spin", defaults={"duration_min": 45}
        )
        room, _ = Room.objects.get_or_create(
            venue=venue, name="Studio", defaults={"capacity": 1}
        )
        return ScheduledClass.objects.create(
            venue=venue,
            class_type=class_type,
            room=room,
            teacher=_user("teacher"),
            starts_at=start,
            ends_at=start + timedelta(hours=1),
        )

    def test_waitlist_query_param(self):
        from passes.models import PassProduct
        from passes.services import issue_pass

        venue = _venue()
        klass = self._full_class(venue)
        first = _member(venue, "first")
        second = _member(venue, "second")
        for user in (first, second):
            product, _ = PassProduct.objects.get_or_create(
                venue=venue,
                name="Pack",
                defaults={"credits_total": 10, "validity_days": 30},
            )
            issue_pass(user, product)
        _client(first).post(
            "/api/v1/bookings/",
            {"scheduled_class": klass.pk, "idempotency_key": "fill-1"},
        )

        response = _client(second).post(
            "/api/v1/bookings/?waitlist=true",
            {"scheduled_class": klass.pk, "idempotency_key": "fill-2"},
        )

        assert response.status_code == 201
        assert response.data["status"] == "waitlisted"

    def test_mine_query_param(self):
        venue = _venue()
        mine = _member(venue, "mine")
        other = _member(venue, "other")

        response = _client(mine).get("/api/v1/bookings/?mine=true")

        assert response.status_code == 200
        assert all(entry["member"] == mine.pk for entry in response.data)
        assert other.pk not in [entry["member"] for entry in response.data]


class TestClassVenueParam:
    def test_mismatched_venue_404(self):
        venue = _venue()

        response = _client(_member(venue)).get("/api/v1/classes/?venue=elsewhere")

        assert response.status_code == 404

    def test_matching_venue_200(self):
        venue = _venue()

        response = _client(_member(venue)).get("/api/v1/classes/?venue=downtown")

        assert response.status_code == 200


class TestSlotsRange:
    def test_from_to_range(self):
        from scheduling.appointments import AvailabilityRule, Resource

        venue = _venue()
        resource = Resource.objects.create(
            venue=venue, name="Table", type=Resource.Kind.EQUIPMENT
        )
        AvailabilityRule.objects.create(
            resource=resource, weekday=0, start_time="09:00", end_time="10:00"
        )

        response = _client(_member(venue)).get(
            "/api/v1/availability/slots/",
            {
                "resource": resource.pk,
                "from": "2026-10-26T00:00:00Z",
                "to": "2026-11-02T00:00:00Z",
            },
        )

        assert response.status_code == 200
        assert len(response.data) == 2  # both Mondays in range


class TestCalendarRoom:
    def test_room_filters_classes(self):
        from scheduling.models import ClassType, Room, ScheduledClass

        venue = _venue()
        teacher = _user("teacher")
        start = timezone.now() + timedelta(days=1)
        class_type, _ = ClassType.objects.get_or_create(
            venue=venue, name="Spin", defaults={"duration_min": 45}
        )
        room_a = Room.objects.create(venue=venue, name="A", capacity=20)
        room_b = Room.objects.create(venue=venue, name="B", capacity=20)
        for room, tutor in ((room_a, teacher), (room_b, _user("teacher-b"))):
            ScheduledClass.objects.create(
                venue=venue,
                class_type=class_type,
                room=room,
                teacher=tutor,
                starts_at=start,
                ends_at=start + timedelta(hours=1),
            )
        now = timezone.now()

        response = _client(_member(venue)).get(
            "/api/v1/calendar/",
            {
                "from": now.isoformat(),
                "to": (now + timedelta(days=7)).isoformat(),
                "room": room_a.pk,
            },
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["room"] == "A"
