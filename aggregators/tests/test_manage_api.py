import pytest

from aggregators.models import Aggregator, AggregatorEventLog
from aggregators.tokens import verify
from organizations.models import OrgRole
from tests.factories import api_client, make_venue, user_with_role

pytestmark = pytest.mark.django_db

#  Manage seam: staff CRUD + rotation for partners (4je built the channel,
#  not its back-office). Raw tokens surface exactly once — at create and
#  at rotate — and are never stored.


class TestAggregatorCrud:
    def test_staff_creates_partner_with_single_token_viewing(self):
        venue = make_venue("manage")

        response = api_client(
            user_with_role(venue, "owner", username="owner"), venue_slug="manage"
        ).post(
            "/api/v1/staff/aggregators/",
            {
                "slug": "gymhopper",
                "name": "Gymhopper",
                "seat_allotment": 4,
            },
        )

        assert response.status_code == 201
        raw = response.json()["api_token"]
        partner = Aggregator.objects.get(slug="gymhopper")
        assert raw and verify(raw, partner.api_token_hash)
        assert partner.api_token_hash != raw

    def test_create_does_not_store_plaintext(self):
        venue = make_venue("manage-plain")
        staff = user_with_role(venue, "owner", username="owner2")

        response = api_client(staff, venue_slug="manage-plain").post(
            "/api/v1/staff/aggregators/",
            {"slug": "plain", "name": "Plain", "seat_allotment": 2},
        )

        assert response.status_code == 201
        stored = Aggregator.objects.get(slug="plain").api_token_hash
        assert len(stored) == 64

    def test_member_cannot_create(self):
        venue = make_venue("manage-no")

        response = api_client(user_with_role(venue, OrgRole.Role.MEMBER)).post(
            "/api/v1/staff/aggregators/",
            {"slug": "nope", "name": "Nope", "seat_allotment": 1},
        )

        assert response.status_code in (403, 404)

    def test_rotate_invalidates_old_token(self):
        venue = make_venue("manage-rot")
        staff = user_with_role(venue, "owner", username="owner3")
        client = api_client(staff, venue_slug="manage-rot")
        created = client.post(
            "/api/v1/staff/aggregators/",
            {"slug": "rot", "name": "Rot", "seat_allotment": 2},
        )
        old_raw = created.json()["api_token"]

        rotated = client.post("/api/v1/staff/aggregators/rot/rotate/")

        assert rotated.status_code == 200
        fresh_raw = rotated.json()["api_token"]
        assert fresh_raw != old_raw
        partner = Aggregator.objects.get(slug="rot")
        assert verify(fresh_raw, partner.api_token_hash)
        assert not verify(old_raw, partner.api_token_hash)

    def test_event_log_lists_partner_calls(self):
        venue = make_venue("manage-log")
        staff = user_with_role(venue, "owner", username="owner4")
        client = api_client(staff, venue_slug="manage-log")
        client.post(
            "/api/v1/staff/aggregators/",
            {"slug": "logged", "name": "Logged", "seat_allotment": 2},
        )
        partner = Aggregator.objects.get(slug="logged")
        AggregatorEventLog.objects.create(
            aggregator=partner, method="POST", path="/x/", status_code=201
        )

        response = client.get("/api/v1/staff/aggregators/logged/events/")

        assert response.status_code == 200
        assert response.json()[0]["status_code"] == 201
