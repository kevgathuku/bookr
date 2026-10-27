import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from test_staff_api import _class, _member, _venue

from aggregators.models import Aggregator, AggregatorBooking
from aggregators.tokens import new_token, rotate, verify
from booking.models import Booking

pytestmark = pytest.mark.django_db


def _partner(slug="classpass"):
    user = get_user_model().objects.create_user(username=f"svc-{slug}")
    return Aggregator.objects.create(
        slug=slug,
        name=slug.title(),
        api_token_hash="x",
        seat_allotment=4,
        service_user=user,
    )


class TestTokens:
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
        venue = _venue()
        partner = _partner()
        booking = Booking.objects.create(
            member=_member(venue),
            venue=venue,
            scheduled_class=_class(venue),
            status=Booking.Status.CONFIRMED,
            idempotency_key="agg-ext-1",
        )
        AggregatorBooking.objects.create(
            aggregator=partner, external_id="ext-1", booking=booking
        )

        with pytest.raises(IntegrityError):
            AggregatorBooking.objects.create(
                aggregator=partner, external_id="ext-1", booking=booking
            )


def _setup_partner():
    from rest_framework.test import APIClient

    venue = _venue("agg-venue")
    klass = _class(venue)
    raw, token_hash = new_token()
    partner = _partner("gymhopper")
    partner.api_token_hash = token_hash
    partner.save(update_fields=["api_token_hash"])
    client = APIClient()
    client.defaults["HTTP_X_PARTNER_TOKEN"] = raw
    return klass, partner, client


class TestPartnerBookings:
    def test_same_external_id_twice_is_one_booking(self):
        klass, _partner, client = _setup_partner()
        url = "/api/v1/aggregators/gymhopper/bookings/"
        body = {"scheduled_class": klass.pk, "external_id": "ext-9"}

        first = client.post(url, body)
        second = client.post(url, body)

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_over_allotment_is_409(self):

        klass, partner, client = _setup_partner()
        partner.seat_allotment = 1
        partner.save(update_fields=["seat_allotment"])
        url = "/api/v1/aggregators/gymhopper/bookings/"

        assert (
            client.post(
                url, {"scheduled_class": klass.pk, "external_id": "a"}
            ).status_code
            == 201
        )
        over = client.post(url, {"scheduled_class": klass.pk, "external_id": "b"})

        assert over.status_code == 409

    def test_bad_token_is_401(self):
        from rest_framework.test import APIClient

        klass, _partner, _client = _setup_partner()
        stranger = APIClient()
        stranger.defaults["HTTP_X_PARTNER_TOKEN"] = "bogus"

        response = stranger.post(
            "/api/v1/aggregators/gymhopper/bookings/",
            {"scheduled_class": klass.pk, "external_id": "x"},
        )

        assert response.status_code == 401

    def test_rotated_token_401s_old(self):
        klass, partner, client = _setup_partner()
        _fresh_raw, fresh_hash = rotate()
        partner.api_token_hash = fresh_hash
        partner.save(update_fields=["api_token_hash"])

        response = client.post(
            "/api/v1/aggregators/gymhopper/bookings/",
            {"scheduled_class": klass.pk, "external_id": "x"},
        )

        assert response.status_code == 401


class TestPartnerCancel:
    def test_cancel_inside_cutoff_cancels(self):
        from rest_framework.test import APIClient

        venue = _venue("agg-cancel")
        klass = _class(venue)
        raw, token_hash = new_token()
        partner = _partner("cancelco")
        partner.api_token_hash = token_hash
        partner.save(update_fields=["api_token_hash"])
        client = APIClient()
        client.defaults["HTTP_X_PARTNER_TOKEN"] = raw
        url = "/api/v1/aggregators/cancelco/bookings/"
        assert (
            client.post(
                url, {"scheduled_class": klass.pk, "external_id": "c1"}
            ).status_code
            == 201
        )

        cancelled = client.post(f"{url}c1/cancel/")

        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

    def test_late_cancel_bills_partner_without_passes(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.test import APIClient

        from passes.models import CreditLedger

        venue = _venue("agg-late")
        klass = _class(venue)
        klass.starts_at = timezone.now() + timedelta(minutes=10)
        klass.ends_at = klass.starts_at + timedelta(hours=1)
        klass.save(update_fields=["starts_at", "ends_at"])
        raw, token_hash = new_token()
        partner = _partner("lateco")
        partner.api_token_hash = token_hash
        partner.save(update_fields=["api_token_hash"])
        client = APIClient()
        client.defaults["HTTP_X_PARTNER_TOKEN"] = raw
        url = "/api/v1/aggregators/lateco/bookings/"
        assert (
            client.post(
                url, {"scheduled_class": klass.pk, "external_id": "l1"}
            ).status_code
            == 201
        )

        cancelled = client.post(f"{url}l1/cancel/")

        assert cancelled.json()["status"] == "cancelled_late"
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
        from rest_framework.test import APIClient

        from aggregators.models import AggregatorBooking, AggregatorEventLog
        from booking.models import Booking

        venue = _venue("agg-replay")
        klass = _class(venue)
        raw, token_hash = new_token()
        partner = _partner("replayco")
        partner.api_token_hash = token_hash
        partner.save(update_fields=["api_token_hash"])
        client = APIClient()
        client.defaults["HTTP_X_PARTNER_TOKEN"] = raw
        url = "/api/v1/aggregators/replayco/bookings/"
        client.post(url, {"scheduled_class": klass.pk, "external_id": "r1"})
        client.post(url, {"scheduled_class": klass.pk, "external_id": "r1"})
        client.post(f"{url}r1/cancel/")

        calls = list(
            AggregatorEventLog.objects.filter(aggregator=partner).order_by("id")
        )
        assert [call.status_code for call in calls] == [201, 200, 200]
        link = AggregatorBooking.objects.get(aggregator=partner, external_id="r1")
        assert link.booking.status == Booking.Status.CANCELLED


class TestReviewFixes:
    def test_retry_with_different_class_is_409(self):
        klass, _partner, client = _setup_partner()
        other = _class(_venue("other-venue"))
        url = "/api/v1/aggregators/gymhopper/bookings/"

        assert (
            client.post(
                url, {"scheduled_class": klass.pk, "external_id": "m1"}
            ).status_code
            == 201
        )
        clash = client.post(url, {"scheduled_class": other.pk, "external_id": "m1"})

        assert clash.status_code == 409

    def test_partner_cancel_promotes_waitlisted_member(self):
        from booking.models import Booking
        from passes.models import PassProduct
        from passes.services import issue_pass

        klass, _partner, client = _setup_partner()
        member = _member(klass.venue, "waiter")
        from organizations.models import VenuePolicy

        VenuePolicy.objects.get_or_create(
            venue=klass.venue, valid_until=None, defaults={"waitlist_hold_minutes": 5}
        )
        product, _ = PassProduct.objects.get_or_create(
            venue=klass.venue,
            name="Pack",
            defaults={"credits_total": 10, "validity_days": 30},
        )
        issue_pass(member, product)
        waitlisted = Booking.objects.create(
            member=member,
            venue=klass.venue,
            scheduled_class=klass,
            status=Booking.Status.WAITLISTED,
            idempotency_key="agg-wait-1",
        )
        url = "/api/v1/aggregators/gymhopper/bookings/"
        assert (
            client.post(
                url, {"scheduled_class": klass.pk, "external_id": "p1"}
            ).status_code
            == 201
        )

        assert client.post(f"{url}p1/cancel/").status_code == 200

        waitlisted.refresh_from_db()
        assert waitlisted.status == Booking.Status.CONFIRMED

    def test_partner_schedule_hides_teacher_username(self):
        _klass, _partner, client = _setup_partner()

        response = client.get("/api/v1/aggregators/gymhopper/schedule/")

        assert response.status_code == 200
        assert response.json() != []
        assert "teacher" not in response.json()[0]
        assert "teacher_name" not in response.json()[0]
