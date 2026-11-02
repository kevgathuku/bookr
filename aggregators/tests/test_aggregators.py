from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from aggregators.models import AggregatorBooking, AggregatorEventLog
from aggregators.tokens import new_token, rotate, verify
from booking.models import Booking
from organizations.models import OrgRole
from passes.models import CreditLedger
from tests.factories import (
    AggregatorFactory,
    ClassOfferingFactory,
    ClassSessionFactory,
    PlanMembershipFactory,
    UserFactory,
    VenueFactory,
    user_with_role,
)

pytestmark = pytest.mark.django_db


def _partner(slug="classpass"):
    return AggregatorFactory(
        slug=slug,
        name=slug.title(),
        service_user=UserFactory(username=f"svc-{slug}"),
    )


def _session(venue, teacher=None, **overrides):
    offering = ClassOfferingFactory(
        venue=venue,
        teacher=teacher or UserFactory(username=f"teacher-{venue.slug}"),
        title="Spin",
    )
    defaults = {"starts_at": timezone.now() + timedelta(days=1)}
    defaults.update(overrides)
    return ClassSessionFactory(offering=offering, **defaults)


def _setup_partner():
    venue = VenueFactory(slug="agg-venue", name="Agg Venue")
    session = _session(venue)
    raw, token_hash = new_token()
    partner = _partner("gymhopper")
    partner.api_token_hash = token_hash
    partner.save(update_fields=["api_token_hash"])
    client = APIClient()
    client.defaults["HTTP_X_PARTNER_TOKEN"] = raw
    return session, partner, client


class TestTokens:
    def test_aggregator_str(self):
        assert str(_partner("classpass")) == "classpass"

    def test_event_log_newest_first(self):
        partner = _partner("logpass")
        old = AggregatorEventLog.objects.create(
            aggregator=partner, method="POST", path="/old", status_code=200
        )
        AggregatorEventLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )
        fresh = AggregatorEventLog.objects.create(
            aggregator=partner, method="POST", path="/new", status_code=200
        )

        assert list(AggregatorEventLog.objects.all()) == [fresh, old]

    def test_verify_accepts_issued_token(self):
        raw, token_hash = new_token()

        assert verify(raw, token_hash) is True
        assert verify(f"{raw}x", token_hash) is False

    def test_rotate_invalidates_old_token(self):
        old_raw, old_hash = new_token()
        partner = _partner()
        partner.api_token_hash = old_hash
        partner.save(update_fields=["api_token_hash"])

        fresh_raw, fresh_hash = rotate()
        partner.api_token_hash = fresh_hash
        partner.save(update_fields=["api_token_hash"])

        assert verify(fresh_raw, fresh_hash) is True
        assert verify(old_raw, fresh_hash) is False

    def test_external_id_unique_per_partner(self):
        venue = VenueFactory()
        partner = _partner()
        member = UserFactory(username="agg-member")
        membership = PlanMembershipFactory(user=member)
        session = ClassSessionFactory(offering=ClassOfferingFactory(venue=venue))
        booking = Booking.objects.create(
            session=session, member=member, membership=membership
        )
        AggregatorBooking.objects.create(
            aggregator=partner, external_id="ext-1", booking=booking
        )

        with pytest.raises(IntegrityError):
            AggregatorBooking.objects.create(
                aggregator=partner, external_id="ext-1", booking=booking
            )


class TestPartnerBookings:
    def test_same_external_id_twice_is_one_booking(self):
        session, _partner, client = _setup_partner()
        url = "/api/v1/aggregators/gymhopper/bookings/"
        body = {"session": session.pk, "external_id": "ext-9"}

        first = client.post(url, body)
        second = client.post(url, body)

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_over_allotment_is_409(self):
        session, partner, client = _setup_partner()
        partner.seat_allotment = 1
        partner.save(update_fields=["seat_allotment"])
        url = "/api/v1/aggregators/gymhopper/bookings/"

        assert (
            client.post(url, {"session": session.pk, "external_id": "a"}).status_code
            == 201
        )
        over = client.post(url, {"session": session.pk, "external_id": "b"})

        assert over.status_code == 409

    def test_bad_token_is_401(self):
        session, _partner, _client = _setup_partner()
        stranger = APIClient()
        stranger.defaults["HTTP_X_PARTNER_TOKEN"] = "bogus"

        response = stranger.post(
            "/api/v1/aggregators/gymhopper/bookings/",
            {"session": session.pk, "external_id": "x"},
        )

        assert response.status_code == 401

    def test_rotated_token_401s_old(self):
        session, partner, client = _setup_partner()
        _fresh_raw, fresh_hash = rotate()
        partner.api_token_hash = fresh_hash
        partner.save(update_fields=["api_token_hash"])

        response = client.post(
            "/api/v1/aggregators/gymhopper/bookings/",
            {"session": session.pk, "external_id": "x"},
        )

        assert response.status_code == 401


class TestPartnerCancel:
    def _client_for(self, slug, name="cancelco"):
        venue = VenueFactory(slug=slug, name=slug.title())
        session = _session(venue)
        raw, token_hash = new_token()
        partner = _partner(name)
        partner.api_token_hash = token_hash
        partner.save(update_fields=["api_token_hash"])
        client = APIClient()
        client.defaults["HTTP_X_PARTNER_TOKEN"] = raw
        return session, partner, client

    def test_cancel_inside_cutoff_cancels(self):
        session, _partner, client = self._client_for("agg-cancel")
        url = "/api/v1/aggregators/cancelco/bookings/"
        assert (
            client.post(url, {"session": session.pk, "external_id": "c1"}).status_code
            == 201
        )

        cancelled = client.post(f"{url}c1/cancel/")

        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

    def test_late_cancel_marks_late_without_charges(self):
        from booking.models import CancellationPolicy

        session, _partner, client = self._client_for("agg-late", "lateco")
        CancellationPolicy.objects.create(
            organization=session.offering.venue.organization,
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.LOSE_CREDIT,
        )
        session.starts_at = timezone.now() + timedelta(minutes=10)
        session.save(update_fields=["starts_at"])
        url = "/api/v1/aggregators/lateco/bookings/"
        assert (
            client.post(url, {"session": session.pk, "external_id": "l1"}).status_code
            == 201
        )

        cancelled = client.post(f"{url}l1/cancel/")

        assert cancelled.json()["status"] == "late_cancelled"
        assert CreditLedger.objects.count() == 0


class TestWebhooks:
    def test_signature_verifies_and_rejects_tampering(self):
        from aggregators.webhooks import sign, verify_signature

        body = b'{"event":"booking.created"}'

        assert verify_signature("secret", body, sign("secret", body)) is True
        assert verify_signature("secret", body, "0" * 64) is False
        tampered = body.replace(b"created", b"tampered")
        assert verify_signature("secret", tampered, sign("secret", body)) is False


class TestWebhookSend:
    def test_send_signs_body_and_posts(self):
        from unittest import mock

        from aggregators.webhooks import SIGNATURE_HEADER, send_webhook, sign

        with mock.patch("aggregators.webhooks.urlopen") as opener:
            send_webhook(
                "https://partner.example/hook", "secret", "booking.created", {"a": 1}
            )
            request = opener.call_args[0][0]
        headers = {key.lower(): value for key, value in request.header_items()}
        assert sign("secret", request.data) == headers[SIGNATURE_HEADER.lower()]


class TestEventLogReplay:
    def test_log_replays_to_identical_booking_state(self):
        session, partner, client = _setup_partner()
        url = "/api/v1/aggregators/gymhopper/bookings/"
        client.post(url, {"session": session.pk, "external_id": "r1"})
        client.post(url, {"session": session.pk, "external_id": "r1"})
        client.post(f"{url}r1/cancel/")

        calls = list(
            AggregatorEventLog.objects.filter(aggregator=partner).order_by("id")
        )
        assert [call.status_code for call in calls] == [201, 200, 200]
        link = AggregatorBooking.objects.get(aggregator=partner, external_id="r1")
        assert link.booking.status == Booking.Status.CANCELLED


class TestReviewFixes:
    def test_retry_with_different_session_is_409(self):
        session, _partner, client = _setup_partner()
        other = _session(VenueFactory(slug="other-venue", name="Other"))
        url = "/api/v1/aggregators/gymhopper/bookings/"

        assert (
            client.post(url, {"session": session.pk, "external_id": "m1"}).status_code
            == 201
        )
        clash = client.post(url, {"session": other.pk, "external_id": "m1"})

        assert clash.status_code == 409

    def test_partner_schedule_hides_teacher_identity(self):
        _session, _partner, client = _setup_partner()

        response = client.get("/api/v1/aggregators/gymhopper/schedule/")

        assert response.status_code == 200
        assert response.json() != []
        assert "teacher" not in response.json()[0]
        assert "teacher_name" not in response.json()[0]


class TestStaffGatesOnRoles:
    """Aggregator back-office honors OrgRole staff ranks, not just rows."""

    def test_org_role_manager_lists_partners(self):
        venue = VenueFactory()
        manager = user_with_role(venue, OrgRole.Role.MANAGER, username="agg-manager")
        client = APIClient()
        client.force_authenticate(user=manager)
        client.defaults["HTTP_X_VENUE_SLUG"] = venue.slug

        response = client.get("/api/v1/staff/aggregators/")

        assert response.status_code == 200

    def test_org_role_member_cannot_list_partners(self):
        venue = VenueFactory()
        member = user_with_role(venue, OrgRole.Role.MEMBER, username="agg-member")
        client = APIClient()
        client.force_authenticate(user=member)
        client.defaults["HTTP_X_VENUE_SLUG"] = venue.slug

        response = client.get("/api/v1/staff/aggregators/")

        assert response.status_code == 403
