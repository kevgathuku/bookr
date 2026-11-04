import pytest

from organizations.models import OrgRole
from passes.models import CreditLedger
from tests.factories import api_client, make_venue, user_with_role, with_credit_pack

pytestmark = pytest.mark.django_db

#  Membership/adjust seam (bookr-9pt): the two endpoints the nightly
#  browser suite needs that the remodel never built.
#  - GET /api/v1/memberships/ lists the caller's own plan memberships;
#    ?member=<id> lets covering staff list one member's (member asking
#    for another's gets nothing to leak ids).
#  - POST /api/v1/ledger/adjust/ {membership, delta, reason} is the
#    desk goodwill path: reason required, delta nonzero, result stays
#    non-negative, writes one ADJUSTMENT row stamped by the actor.


def _world(slug="adjust-world"):
    venue = make_venue(slug)
    member = user_with_role(venue, OrgRole.Role.MEMBER, f"member-{slug}", org_wide=True)
    return venue, member


class TestMembershipList:
    def test_member_sees_own_memberships(self):
        venue, member = _world("mine-list")
        membership = with_credit_pack(member, venue)

        response = api_client(member, venue_slug="mine-list").get(
            "/api/v1/memberships/"
        )

        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert rows[membership.pk]["credits_remaining"] == 10
        assert rows[membership.pk]["plan_name"] == membership.plan.name

    def test_staff_lists_one_member(self):
        venue, member = _world("staff-list")
        membership = with_credit_pack(member, venue)
        staffer = user_with_role(venue, OrgRole.Role.FRONTDESK, org_wide=True)

        response = api_client(staffer, venue_slug="staff-list").get(
            f"/api/v1/memberships/?member={member.pk}"
        )

        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [membership.pk]

    def test_member_cannot_list_another_member(self):
        venue, member = _world("no-leak")
        other = user_with_role(
            venue, OrgRole.Role.MEMBER, "other-no-leak", org_wide=True
        )

        response = api_client(member, venue_slug="no-leak").get(
            f"/api/v1/memberships/?member={other.pk}"
        )

        assert response.status_code == 404


class TestLedgerAdjust:
    def test_desk_adjust_writes_row_and_moves_balance(self):
        venue, member = _world("adjust-ok")
        membership = with_credit_pack(member, venue, credits=10)
        staffer = user_with_role(venue, OrgRole.Role.FRONTDESK, org_wide=True)

        response = api_client(staffer, venue_slug="adjust-ok").post(
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
        membership = with_credit_pack(member, venue)
        staffer = user_with_role(venue, OrgRole.Role.FRONTDESK, org_wide=True)

        response = api_client(staffer, venue_slug="adjust-reason").post(
            "/api/v1/ledger/adjust/",
            {"membership": membership.pk, "delta": 1, "reason": " "},
        )

        assert response.status_code == 400

    def test_member_cannot_adjust(self):
        venue, member = _world("adjust-member")
        membership = with_credit_pack(member, venue)

        response = api_client(member, venue_slug="adjust-member").post(
            "/api/v1/ledger/adjust/",
            {"membership": membership.pk, "delta": 1, "reason": "goodwill"},
        )

        assert response.status_code in (403, 404)


class TestLedgerGrants:
    """POST /api/v1/ledger/grants/ mints one grant; same key twice is one."""

    def test_desk_grant_mints_membership(self):
        venue, member = _world("grant-ok")
        staffer = user_with_role(venue, OrgRole.Role.FRONTDESK, org_wide=True)

        response = api_client(staffer, venue_slug="grant-ok").post(
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
        staffer = user_with_role(venue, OrgRole.Role.FRONTDESK, org_wide=True)
        payload = {
            "member": member.pk,
            "credits": 2,
            "note": "comp",
            "incident_key": "grant-9",
        }

        first = api_client(staffer, venue_slug="grant-idem").post(
            "/api/v1/ledger/grants/", payload
        )
        second = api_client(staffer, venue_slug="grant-idem").post(
            "/api/v1/ledger/grants/", payload
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_member_cannot_grant(self):
        _, member = _world("grant-member")

        response = api_client(member, venue_slug="grant-member").post(
            "/api/v1/ledger/grants/",
            {"member": member.pk, "credits": 2, "incident_key": "grant-x"},
        )

        assert response.status_code in (403, 404)
