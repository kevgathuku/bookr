from datetime import timedelta
from unittest import mock

import pytest
from django.db import OperationalError
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from access.models import AccessEvent, AccessPoint
from access.services import decide
from booking.models import Booking
from booking.services import book_session
from organizations.models import OrgRole
from passes.models import PlanType
from tests.factories import (  # noqa: WPS235 — access tests build every domain object via factories
    OrganizationFactory,
    OrgRoleFactory,
    PlanFactory,
    PlanMembershipFactory,
    UserFactory,
    VenueFactory,
    api_client,
    make_member,
    make_session,
    make_venue,
    user_with_role,
)

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


def _point(venue):
    point = AccessPoint.objects.create(
        venue=venue, name="Front Door", controller_id="door-1"
    )
    token = point.set_token()
    point.save()
    return point, token


def _check(token, member_pk, point_pk):
    client = APIClient()
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {token}"
    return client.post(
        "/api/access/check/",
        {"access_point": point_pk, "member": member_pk},
        format="json",
    )


class TestAccessPointModel:
    def test_token_roundtrip(self):
        point, token = _point(make_venue("token"))

        assert point.check_token(token) is True
        assert point.check_token("wrong-token") is False

    def test_blank_hash_denies(self):
        point = AccessPoint.objects.create(
            venue=make_venue("blank"), name="No Token", controller_id="door-9"
        )

        assert point.check_token("anything") is False

    def test_str(self):
        point, _token = _point(make_venue("str"))

        assert str(point) == f"Front Door @ {point.venue}"

    def test_controller_unique_per_venue(self):
        from django.db import IntegrityError

        venue = make_venue("dup")
        _point(venue)

        with pytest.raises(IntegrityError):
            AccessPoint.objects.create(
                venue=venue, name="Back Door", controller_id="door-1"
            )

    def test_event_str_and_newest_first(self):
        venue = make_venue("events")
        point, _token = _point(venue)
        member = make_member("event-member", venue, credits=5)
        old = AccessEvent.objects.create(
            access_point=point, member=member, granted=False, reason="no_access"
        )
        AccessEvent.objects.filter(pk=old.pk).update(
            occurred_at=timezone.now() - timedelta(hours=1)
        )
        fresh = AccessEvent.objects.create(
            access_point=point, member=member, granted=True, reason="active_pass"
        )

        assert str(fresh) == f"{point}: grant {member} (active_pass)"
        assert list(AccessEvent.objects.all()) == [fresh, old]


class TestGrantDeny:
    def test_active_pass_grants_and_logs(self, venue):
        point, token = _point(venue)
        member = make_member("member", venue, credits=5)

        response = _check(token, member.pk, point.pk)

        assert response.status_code == 200
        assert response.data["granted"] is True
        event = AccessEvent.objects.get(access_point=point, member=member)
        assert (event.granted, event.reason) == (True, "active_pass")

    def test_live_booking_window_grants(self, venue):
        point, token = _point(venue)
        member = make_member("dropin", venue, credits=5)
        session = make_session(venue, starts_at=timezone.now() + timedelta(minutes=10))
        book_session(member=member, session=session)
        # Expire the plan after booking: the live booking alone must grant.
        membership = member.plan_memberships.get()
        membership.starts_on = timezone.now().date() - timedelta(days=60)
        membership.valid_until = timezone.now().date() - timedelta(days=1)
        membership.save(update_fields=["starts_on", "valid_until"])

        response = _check(token, member.pk, point.pk)

        assert response.data["granted"] is True
        assert AccessEvent.objects.get(member=member).reason == "live_booking"

    def test_held_booking_denies_door(self, venue):
        point, token = _point(venue)
        member = make_member("holder", venue, credits=0)
        session = make_session(venue, starts_at=timezone.now() + timedelta(minutes=10))
        membership = member.plan_memberships.get()
        Booking.objects.create(
            session=session,
            member=member,
            membership=membership,
            credits_spent=0,
            status=Booking.Status.HELD,
            hold_expires_at=timezone.now() + timedelta(hours=1),
        )

        response = _check(token, member.pk, point.pk)

        assert response.data["granted"] is False
        assert AccessEvent.objects.get(member=member).reason == "no_access"

    def test_staff_grants_without_pass_or_booking(self, venue):
        point, token = _point(venue)
        staff = user_with_role(venue, OrgRole.Role.MANAGER, username="manager")

        response = _check(token, staff.pk, point.pk)

        assert response.data["granted"] is True
        assert AccessEvent.objects.get(member=staff).reason == "staff"

    def test_stranger_denies_and_logs(self, venue):
        point, token = _point(venue)
        stranger = user_with_role(venue, OrgRole.Role.MEMBER, username="stranger")

        response = _check(token, stranger.pk, point.pk)

        assert response.data["granted"] is False
        assert AccessEvent.objects.get(member=stranger).reason == "no_access"

    def test_bad_token_401(self, venue):
        point, _ = _point(venue)
        member = make_member("member", venue, credits=5)

        response = _check("wrong-token", member.pk, point.pk)

        assert response.status_code == 401

    def test_metric_counts_grants(self, venue):
        point, token = _point(venue)
        member = make_member("member", venue, credits=5)
        before = Client().get("/metrics/").content.decode().count("door_grants_total")

        _check(token, member.pk, point.pk)

        after = Client().get("/metrics/").content.decode().count("door_grants_total")
        assert after > before


class TestPassback:
    def test_replay_within_60s_returns_prior_without_new_event(self, venue):
        point, token = _point(venue)
        member = make_member("member", venue, credits=5)

        first = _check(token, member.pk, point.pk)
        second = _check(token, member.pk, point.pk)

        assert (first.data["granted"], second.data["granted"]) == (True, True)
        assert second.data["reason"] == "passback_replay"
        assert AccessEvent.objects.filter(member=member).count() == 1


class TestFailClosed:
    def test_db_outage_denies(self, venue):
        point, token = _point(venue)
        member = make_member("member", venue, credits=5)

        with mock.patch("access.views.decide", side_effect=OperationalError("db gone")):
            response = _check(token, member.pk, point.pk)

        assert response.status_code == 200
        assert response.data["granted"] is False


class TestRecentEvents:
    def test_frontdesk_reads_member_cannot(self, venue):
        point, token = _point(venue)
        member = make_member("member", venue, credits=5)
        staff = user_with_role(venue, OrgRole.Role.FRONTDESK, username="frontdesk")
        _check(token, member.pk, point.pk)

        staff_view = api_client(staff, venue_slug=venue.slug).get(
            "/api/v1/access/events/"
        )
        member_view = api_client(member, venue_slug=venue.slug).get(
            "/api/v1/access/events/"
        )

        assert staff_view.status_code == 200
        assert len(staff_view.data) == 1
        assert member_view.status_code == 403

    def test_latency_budget(self, venue):
        import time

        point, token = _point(venue)
        member = make_member("member", venue, credits=5)
        _check(token, member.pk, point.pk)  # warm cache
        elapsed = []
        for _ in range(20):
            started = time.perf_counter()
            _check(token, member.pk, point.pk)
            elapsed.append(time.perf_counter() - started)
        elapsed.sort()

        assert elapsed[18] < 1  # p95 proxy; seed-scale must stay far under


class TestStaleGrant:
    def test_cancel_inside_ttl_denies_on_recheck(self):
        # Cancel action itself returns in .4; here the status transition is
        # applied directly to test the decision layer, not the action.
        venue = make_venue("stale-door")
        point, _token = _point(venue)
        member = make_member("stale-member", venue, credits=1)
        session = make_session(venue, starts_at=timezone.now() + timedelta(minutes=10))
        booking = book_session(member=member, session=session)

        verdict = decide(point, member)
        assert verdict.granted is True
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])

        verdict = decide(point, member)

        assert verdict.granted is False


class TestRoleBasedAccess:
    """OrgRole rows grant access: pinned to one venue, org-wide to all."""

    def test_org_role_member_reads_schedule(self):
        venue = VenueFactory()
        user = UserFactory(username="rolemember")
        OrgRoleFactory(
            organization=venue.organization,
            venue=venue,
            user=user,
            role=OrgRole.Role.MEMBER,
        )

        response = api_client(user, venue_slug=venue.slug).get("/api/v1/sessions/")

        assert response.status_code == 200

    def test_org_role_does_not_cross_venues(self):
        org = OrganizationFactory()
        first = VenueFactory(organization=org)
        second = VenueFactory(organization=org)
        user = UserFactory(username="pinned")
        OrgRoleFactory(
            organization=org, venue=first, user=user, role=OrgRole.Role.MEMBER
        )

        response = api_client(user, venue_slug=second.slug).get("/api/v1/sessions/")

        assert response.status_code == 404

    def test_org_wide_role_covers_all_org_venues(self):
        org = OrganizationFactory()
        first = VenueFactory(organization=org)
        second = VenueFactory(organization=org)
        user = UserFactory(username="spanning")
        OrgRoleFactory(
            organization=org, venue=None, user=user, role=OrgRole.Role.MEMBER
        )

        assert (
            api_client(user, venue_slug=first.slug).get("/api/v1/sessions/").status_code
            == 200
        )
        assert (
            api_client(user, venue_slug=second.slug)
            .get("/api/v1/sessions/")
            .status_code
            == 200
        )


class TestDoorPlanMemberships:
    """Door grants on plan validity: monthly by dates, packs by balance."""

    def _check_decide(self, venue, member):

        point, _token = _point(venue)
        return decide(point, member)

    def test_monthly_plan_grants_without_balance(self, venue):
        member = UserFactory(username="monthly")
        plan = PlanFactory(organization=venue.organization, monthly=True)
        PlanMembershipFactory(user=member, plan=plan, credits_remaining=None)

        verdict = self._check_decide(venue, member)

        assert (verdict.granted, verdict.reason) == (True, "active_pass")

    def test_pack_with_balance_grants(self, venue):
        member = UserFactory(username="packholder")
        plan = PlanFactory(
            organization=venue.organization, plan_type=PlanType.CREDIT_PACK
        )
        PlanMembershipFactory(user=member, plan=plan, credits_remaining=3)

        verdict = self._check_decide(venue, member)

        assert verdict.granted is True

    def test_depleted_pack_denies(self, venue):
        member = UserFactory(username="depleted")
        plan = PlanFactory(
            organization=venue.organization, plan_type=PlanType.CREDIT_PACK
        )
        PlanMembershipFactory(user=member, plan=plan, credits_remaining=0)

        verdict = self._check_decide(venue, member)

        assert verdict.granted is False

    def test_org_role_teacher_opens_staff_door(self, venue):
        point, _token = _point(venue)
        teacher = user_with_role(venue, OrgRole.Role.TEACHER, "door-teacher")

        verdict = decide(point, teacher)

        assert (verdict.granted, verdict.reason) == (True, "staff")

    def test_org_role_plain_member_door_denied(self, venue):
        point, _token = _point(venue)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "doormember")

        verdict = decide(point, member)

        assert verdict.granted is False
