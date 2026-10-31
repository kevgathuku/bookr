from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import Organization, OrgRole, Venue

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


_ids = iter(range(1000000))


def _unique(username):
    return f"{username}-{next(_ids)}"


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    return Venue.objects.create(organization=org, slug=slug, name=slug.title())


def _staff(venue, username="manager", role=OrgRole.Role.MANAGER):
    user = get_user_model().objects.create_user(username=_unique(username))
    OrgRole.objects.create(
        organization=venue.organization, venue=venue, user=user, role=role
    )
    return user


def _member(venue, username="member"):
    user = get_user_model().objects.create_user(username=_unique(username))
    OrgRole.objects.create(
        organization=venue.organization,
        venue=venue,
        user=user,
        role=OrgRole.Role.MEMBER,
    )
    return user


def _member_with_plan(venue, username):
    from tests.factories import (
        PlanFactory,
        PlanMembershipFactory,
        UserFactory,
    )

    member = UserFactory(username=username)
    plan = PlanFactory(organization=venue.organization)
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

    def test_search_finds_spanning_member(self):
        venue = _venue()
        spanning = _member(venue, "spanning-sue")
        OrgRole.objects.filter(user=spanning).update(venue=None)

        response = _client(_staff(venue)).get("/api/v1/members/search/?q=sue")

        assert response.status_code == 200
        assert any(
            row["username"].startswith("spanning-sue") for row in response.json()
        )

    def test_member_cannot_search(self):
        venue = _venue()

        response = _client(_member(venue)).get("/api/v1/members/search/?q=a")

        assert response.status_code in (403, 404)


class TestDeskCancelFlows:
    def _client(self, user, venue):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_VENUE_SLUG"] = venue.slug
        return client

    def _world(self, slug="desk-flow"):
        from organizations.models import OrgRole
        from tests.factories import OrgRoleFactory, UserFactory, VenueFactory

        venue = VenueFactory(slug=slug)
        desk = UserFactory(username=f"desk-{slug}")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=desk,
            role=OrgRole.Role.FRONTDESK,
        )
        return venue, desk

    def _book(self, venue, username, credits=10):
        from datetime import timedelta

        from django.utils import timezone

        from booking.services import book_session
        from organizations.models import OrgRole
        from tests.factories import (
            ClassOfferingFactory,
            ClassSessionFactory,
            OrgRoleFactory,
            PlanFactory,
            PlanMembershipFactory,
            UserFactory,
        )

        member = UserFactory(username=username)
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        plan = PlanFactory(organization=venue.organization)
        PlanMembershipFactory(user=member, plan=plan, credits_remaining=credits)
        offering = ClassOfferingFactory(venue=venue, duration_minutes=60)
        session = ClassSessionFactory(
            offering=offering,
            starts_at=timezone.now() + timedelta(hours=2),
        )
        booking = book_session(session=session, member=member)
        return member, booking, session

    def test_desk_cancels_on_behalf_late_forfeits(self):
        from booking.models import CancellationPolicy

        venue, desk = self._world()
        _member, booking, _session = self._book(venue, "m-flow")
        CancellationPolicy.objects.create(
            organization=venue.organization,
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.LOSE_CREDIT,
        )

        response = self._client(desk, venue).post(
            f"/api/v1/bookings/{booking.pk}/cancel/",
            {"staff_override": True, "reason": "called in sick"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["enforcement_applied"] == "lose_credit"
        assert response.data["credits_refunded"] == 0
        assert response.data["snapshot"]["on_behalf_of"] is True

    def test_desk_contradiction_rejected(self):
        venue, desk = self._world(slug="desk-contra")
        _member, booking, _session = self._book(venue, "m-contra")

        # Staff's own decision carries no penalty: nothing to waive.
        response = self._client(desk, venue).post(
            f"/api/v1/bookings/{booking.pk}/cancel/",
            {"waive_penalty": True, "reason": "oops"},
            format="json",
        )

        assert response.status_code == 409

    def test_member_cancels_own_booking(self):
        venue, _desk = self._world(slug="desk-own")
        member, booking, _session = self._book(venue, "m-own")

        response = self._client(member, venue).post(
            f"/api/v1/bookings/{booking.pk}/cancel/",
            {"reason": "change of plans"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["enforcement_applied"] == "none"

    def test_member_cancel_needs_no_body(self):
        # The member UI posts a bare cancel; every field has a default.
        venue, _desk = self._world(slug="desk-bare")
        member, booking, _session = self._book(venue, "m-bare")

        response = self._client(member, venue).post(
            f"/api/v1/bookings/{booking.pk}/cancel/"
        )

        assert response.status_code == 200
        assert response.data["cause"] == "member_cancel"

    def test_desk_waives_forfeit(self):
        from booking.models import CancellationPolicy

        venue, desk = self._world(slug="desk-waive")
        member, booking, _session = self._book(venue, "m-waive")
        CancellationPolicy.objects.create(
            organization=venue.organization,
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.LOSE_CREDIT,
        )
        record_id = (
            self._client(member, venue)
            .post(
                f"/api/v1/bookings/{booking.pk}/cancel/",
                {"reason": "overslept"},
                format="json",
            )
            .data["id"]
        )

        response = self._client(desk, venue).post(
            f"/api/v1/records/{record_id}/waive/",
            {"reason": "goodwill"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["penalty_waived"] is False
        assert response.data["enforcement_applied"] == "lose_credit"

    def test_session_cancel_refunds_via_api(self):
        venue, desk = self._world(slug="desk-session")
        _member, _booking, session = self._book(venue, "m-session")

        response = self._client(desk, venue).post(
            f"/api/v1/sessions/{session.pk}/cancel/",
            {"reason": "teacher sick"},
            format="json",
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["credits_refunded"] == 1

    def test_door_marks_no_show_and_check_in(self):
        venue, desk = self._world(slug="desk-door")
        _member, booking, session = self._book(venue, "m-door")
        from datetime import timedelta

        from django.utils import timezone

        session.starts_at = timezone.now() - timedelta(hours=1)
        session.save(update_fields=["starts_at"])

        no_show = self._client(desk, venue).post(
            f"/api/v1/bookings/{booking.pk}/no-show/"
        )
        assert no_show.status_code == 200
        assert no_show.data["cause"] == "no_show"

        booking.refresh_from_db()
        assert booking.status == "no_show"

    def test_door_check_in_stamps_time(self):
        from datetime import timedelta

        from django.utils import timezone

        venue, desk = self._world(slug="desk-checkin")
        _member, booking, session = self._book(venue, "m-checkin")
        session.starts_at = timezone.now() - timedelta(minutes=30)
        session.save(update_fields=["starts_at"])

        checked = self._client(desk, venue).post(
            f"/api/v1/bookings/{booking.pk}/checkin/"
        )

        assert checked.status_code == 200
        assert checked.data["status"] == "attended"
        assert checked.data["checked_in_at"] is not None
        booking.refresh_from_db()
        assert booking.checked_in_at is not None
