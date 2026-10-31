import pytest
from rest_framework.test import APIClient
from test_staff_api import _member, _staff, _venue

from aggregators.models import Aggregator, AggregatorEventLog
from aggregators.tokens import verify

pytestmark = pytest.mark.django_db

#  Manage seam: staff CRUD + rotation for partners (4je built the channel,
#  not its back-office). Raw tokens surface exactly once — at create and
#  at rotate — and are never stored.


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


class TestAggregatorCrud:
    def test_staff_creates_partner_with_single_token_viewing(self):
        venue = _venue("manage")

        response = _client(
            _staff(venue, username="owner", role="owner"), slug="manage"
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
        venue = _venue("manage-plain")
        staff = _staff(venue, username="owner2", role="owner")

        response = _client(staff, slug="manage-plain").post(
            "/api/v1/staff/aggregators/",
            {"slug": "plain", "name": "Plain", "seat_allotment": 2},
        )

        assert response.status_code == 201
        stored = Aggregator.objects.get(slug="plain").api_token_hash
        assert len(stored) == 64

    def test_member_cannot_create(self):
        venue = _venue("manage-no")

        response = _client(_member(venue)).post(
            "/api/v1/staff/aggregators/",
            {"slug": "nope", "name": "Nope", "seat_allotment": 1},
        )

        assert response.status_code in (403, 404)

    def test_rotate_invalidates_old_token(self):

        venue = _venue("manage-rot")
        staff = _staff(venue, username="owner3", role="owner")
        client = _client(staff, slug="manage-rot")
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
        venue = _venue("manage-log")
        staff = _staff(venue, username="owner4", role="owner")
        client = _client(staff, slug="manage-log")
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


class TestCatalogLists:
    def test_staff_lists_rooms_and_class_types(self):
        venue = _venue("manage-catalog")
        staff = _staff(venue, username="owner5", role="owner")
        client = _client(staff, slug="manage-catalog")

        rooms = client.get("/api/v1/rooms/")
        types = client.get("/api/v1/class-types/")

        assert rooms.status_code == 200
        assert types.status_code == 200
