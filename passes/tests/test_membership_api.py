import pytest
from rest_framework.test import APIClient

from organizations.models import OrgRole
from passes.models import CreditLedger

pytestmark = pytest.mark.django_db

#  Membership/adjust seam (bookr-9pt): the two endpoints the nightly
#  browser suite needs that the remodel never built.
#  - GET /api/v1/memberships/ lists the caller's own plan memberships;
#    ?member=<id> lets covering staff list one member's (member asking
#    for another's gets nothing to leak ids).
#  - POST /api/v1/ledger/adjust/ {membership, delta, reason} is the
#    desk goodwill path: reason required, delta nonzero, result stays
#    non-negative, writes one ADJUSTMENT row stamped by the actor.


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


def _world(slug="adjust-world"):
    from tests.factories import VenueFactory, user_with_role

    venue = VenueFactory(slug=slug)
    member = user_with_role(venue, OrgRole.Role.MEMBER, f"member-{slug}", org_wide=True)
    return venue, member


def _membership(venue, member, credits=10):
    from tests.factories import PlanFactory, PlanMembershipFactory

    plan = PlanFactory(organization=venue.organization)
    return PlanMembershipFactory(user=member, plan=plan, credits_remaining=credits)


def _staff(venue, slug, role=OrgRole.Role.FRONTDESK):
    from tests.factories import user_with_role

    return user_with_role(venue, role, f"desk-{slug}", org_wide=True)


class TestMembershipList:
    def test_member_sees_own_memberships(self):
        venue, member = _world("mine-list")
        membership = _membership(venue, member)

        response = _client(member, slug="mine-list").get("/api/v1/memberships/")

        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert rows[membership.pk]["credits_remaining"] == 10
        assert rows[membership.pk]["plan_name"] == membership.plan.name

    def test_staff_lists_one_member(self):
        venue, member = _world("staff-list")
        membership = _membership(venue, member)
        staffer = _staff(venue, "staff-list")

        response = _client(staffer, slug="staff-list").get(
            f"/api/v1/memberships/?member={member.pk}"
        )

        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [membership.pk]

    def test_member_cannot_list_another_member(self):
        venue, member = _world("no-leak")
        from tests.factories import user_with_role

        other = user_with_role(
            venue, OrgRole.Role.MEMBER, "other-no-leak", org_wide=True
        )

        response = _client(member, slug="no-leak").get(
            f"/api/v1/memberships/?member={other.pk}"
        )

        assert response.status_code == 404


class TestLedgerAdjust:
    def test_desk_adjust_writes_row_and_moves_balance(self):
        venue, member = _world("adjust-ok")
        membership = _membership(venue, member, credits=10)
        staffer = _staff(venue, "adjust-ok")

        response = _client(staffer, slug="adjust-ok").post(
            "/api/v1/ledger/adjust/",
            {"membership": membership.pk, "delta": -3, "reason": "goodwill"},
        )

        assert response.status_code == 201, response.content
        membership.refresh_from_db()
        assert membership.credits_remaining == 7
        row = CreditLedger.objects.get(membership=membership)
        assert (row.delta, row.reason, row.note) == (-3, "adjustment", "goodwill")
        assert row.created_by_id == staffer.pk

    def test_adjust_needs_a_reason(self):
        venue, member = _world("adjust-reason")
        membership = _membership(venue, member)
        staffer = _staff(venue, "adjust-reason")

        response = _client(staffer, slug="adjust-reason").post(
            "/api/v1/ledger/adjust/",
            {"membership": membership.pk, "delta": 1, "reason": " "},
        )

        assert response.status_code == 400

    def test_member_cannot_adjust(self):
        venue, member = _world("adjust-member")
        membership = _membership(venue, member)

        response = _client(member, slug="adjust-member").post(
            "/api/v1/ledger/adjust/",
            {"membership": membership.pk, "delta": 1, "reason": "goodwill"},
        )

        assert response.status_code in (403, 404)


class TestLedgerGrants:
    """POST /api/v1/ledger/grants/ mints one grant; same key twice is one."""

    def test_desk_grant_mints_membership(self):
        venue, member = _world("grant-ok")
        staffer = _staff(venue, "grant-ok")

        response = _client(staffer, slug="grant-ok").post(
            "/api/v1/ledger/grants/",
            {
                "member": member.pk,
                "credits": 2,
                "duration_days": 30,
                "note": "late cancel comp",
                "incident_key": "grant-1",
            },
        )

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["credits_remaining"] == 2
        assert body["payment_ref"] == "grant-1"
        assert body["plan_type"] == "complimentary"

    def test_grant_is_idempotent_on_incident_key(self):
        venue, member = _world("grant-idem")
        staffer = _staff(venue, "grant-idem")
        payload = {
            "member": member.pk,
            "credits": 2,
            "note": "comp",
            "incident_key": "grant-9",
        }

        first = _client(staffer, slug="grant-idem").post(
            "/api/v1/ledger/grants/", payload
        )
        second = _client(staffer, slug="grant-idem").post(
            "/api/v1/ledger/grants/", payload
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_member_cannot_grant(self):
        _, member = _world("grant-member")

        response = _client(member, slug="grant-member").post(
            "/api/v1/ledger/grants/",
            {"member": member.pk, "credits": 2, "incident_key": "grant-x"},
        )

        assert response.status_code in (403, 404)
