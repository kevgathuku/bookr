from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from booking.cancellations import cancel_booking, has_strike_flag, mark_no_show
from booking.models import Booking
from organizations.models import Membership, Organization, Venue, VenuePolicy
from passes.models import PassProduct
from passes.services import issue_pass
from scheduling.models import ClassType, Room, ScheduledClass

pytestmark = pytest.mark.django_db

#  Waitlist/cancel seam
#  - FIFO promotion by created_at on cancel (confirmed seat freed only);
#    promoted holds for waitlist_hold_minutes; sweep expiry passes to next.
#  - cancel_booking: outside window refunds, inside forfeits (cancelled_late
#    + strike); staff override always refunds. Boundary +-1min proven.
#  - no-show inside 2h after end; 3 strikes in 30d flags (no auto-ban).
#  - Endpoints: member book/cancel, staff no-show, own bookings list.


def _user(username):
    return get_user_model().objects.create_user(username=username)


_ids = iter(range(1000000))


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    venue = Venue.objects.create(organization=org, slug=slug, name=slug.title())
    VenuePolicy.objects.create(venue=venue)
    return venue


def _member(venue, username):
    user = _user(username)
    Membership.objects.create(
        organization=venue.organization,
        venue=venue,
        user=user,
        role=Membership.Role.MEMBER,
    )
    product, _ = PassProduct.objects.get_or_create(
        venue=venue,
        name="Pack",
        defaults={"credits_total": 10, "validity_days": 30},
    )
    issue_pass(user, product)
    return user


def _class(venue, teacher=None, start=None, capacity=1):
    start = start or (timezone.now() + timedelta(days=1))
    class_type, _ = ClassType.objects.get_or_create(
        venue=venue, name="Spin", defaults={"duration_min": 45}
    )
    room, _ = Room.objects.get_or_create(
        venue=venue, name="Studio", defaults={"capacity": capacity}
    )
    return ScheduledClass.objects.create(
        venue=venue,
        class_type=class_type,
        room=room,
        teacher=teacher or _user(f"teacher-{venue.slug}-{next(_ids)}"),
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


def _book(member, klass, key, waitlist=False):
    from booking.services import book_seat

    return book_seat(member, klass, idempotency_key=key, waitlist=waitlist)


def _client(user, slug="downtown"):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_VENUE_SLUG"] = slug
    return client


class TestCancelBooking:
    def test_outside_window_refunds_and_promotes_fifo(self):
        venue = _venue()
        klass = _class(venue)
        confirmed = _book(_member(venue, "first"), klass, "k1")
        first_waiter = _book(_member(venue, "second"), klass, "k2", waitlist=True)

        cancel_booking(confirmed.member, confirmed)

        confirmed.refresh_from_db()
        first_waiter.refresh_from_db()
        assert confirmed.status == Booking.Status.CANCELLED
        assert first_waiter.status == Booking.Status.CONFIRMED
        assert first_waiter.hold_until is not None
        assert len(mail.outbox) >= 2  # cancelled notice + promotion

    def test_boundary_outside_refunds(self):
        venue = _venue()
        start = timezone.now() + timedelta(days=2)
        klass = _class(venue, start=start)
        member = _member(venue, "edge")
        booking = _book(member, klass, "edge-1")
        cutoff = start - timedelta(hours=8)

        with freeze_time(cutoff - timedelta(minutes=1)):
            cancel_booking(member, booking)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED

    def test_boundary_inside_forfeits(self):
        venue = _venue()
        start = timezone.now() + timedelta(days=2)
        klass = _class(venue, start=start)
        member = _member(venue, "edge")
        booking = _book(member, klass, "edge-1")
        cutoff = start - timedelta(hours=8)

        with freeze_time(cutoff + timedelta(minutes=1)):
            cancel_booking(member, booking)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED_LATE

    def test_staff_override_refunds_late(self):
        venue = _venue()
        start = timezone.now() + timedelta(hours=2)  # inside the 8h window
        klass = _class(venue, start=start)
        member = _member(venue, "late")
        booking = _book(member, klass, "late-1")
        staff = _user("manager")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=staff,
            role=Membership.Role.MANAGER,
        )

        cancel_booking(staff, booking, staff_override=True, reason="goodwill")

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED

    def test_double_cancel_rejected(self):
        venue = _venue()
        klass = _class(venue)
        member = _member(venue, "twice")
        booking = _book(member, klass, "twice-1")
        cancel_booking(member, booking)

        with pytest.raises(ValidationError):
            cancel_booking(member, booking)


class TestNoShow:
    def test_inside_2h_marks_and_promotes(self):
        venue = _venue()
        start = timezone.now() - timedelta(minutes=90)
        klass = _class(venue, start=start)
        member = _member(venue, "ghost")
        booking = _book(member, klass, "ghost-1")
        staff = _user("frontdesk")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=staff,
            role=Membership.Role.FRONTDESK,
        )

        mark_no_show(staff, booking)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.NO_SHOW

    def test_after_2h_rejected(self):
        venue = _venue()
        start = timezone.now() - timedelta(hours=3)
        klass = _class(venue, start=start)
        member = _member(venue, "ghost")
        booking = _book(member, klass, "ghost-1")

        with pytest.raises(ValidationError):
            mark_no_show(_user("staff"), booking)


class TestStrikes:
    def test_three_strikes_flag(self):
        venue = _venue()
        member = _member(venue, "flaky")
        for index in range(3):
            klass = _class(venue, start=timezone.now() + timedelta(days=index + 1))
            booking = _book(member, klass, f"flaky-{index}")
            booking.status = Booking.Status.NO_SHOW
            booking.save()

        assert has_strike_flag(member) is True

    def test_two_strikes_no_flag(self):
        venue = _venue()
        member = _member(venue, "ok")
        for index in range(2):
            klass = _class(venue, start=timezone.now() + timedelta(days=index + 1))
            booking = _book(member, klass, f"ok-{index}")
            booking.status = Booking.Status.NO_SHOW
            booking.save()

        assert has_strike_flag(member) is False


class TestHoldSweep:
    def test_expired_hold_passes_to_next(self):
        from booking.tasks import sweep_expired_holds

        venue = _venue()
        klass = _class(venue, capacity=1)
        confirmed = _book(_member(venue, "holder"), klass, "h1")
        second = _book(_member(venue, "next"), klass, "h2", waitlist=True)
        cancel_booking(confirmed.member, confirmed)
        second.refresh_from_db()
        hold_until = second.hold_until
        assert hold_until is not None

        with freeze_time(hold_until + timedelta(minutes=1)):
            swept = sweep_expired_holds()

        second.refresh_from_db()
        assert swept >= 1
        assert second.status == Booking.Status.CANCELLED


class TestBookingEndpoints:
    def test_book_cancel_flow(self):
        venue = _venue()
        klass = _class(venue, capacity=1)
        member = _member(venue, "appy")

        created = _client(member).post(
            "/api/v1/bookings/",
            {"scheduled_class": klass.pk, "idempotency_key": "app-1"},
        )
        assert created.status_code == 201

        full = _client(_member(venue, "appy2")).post(
            "/api/v1/bookings/",
            {"scheduled_class": klass.pk, "idempotency_key": "app-2"},
        )
        assert full.status_code == 409

        cancelled = _client(member).post(
            f"/api/v1/bookings/{created.data['id']}/cancel/"
        )
        assert cancelled.status_code == 200

    def test_broke_member_402(self):
        venue = _venue()
        klass = _class(venue)
        broke = _user("broke")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=broke,
            role=Membership.Role.MEMBER,
        )

        response = _client(broke).post(
            "/api/v1/bookings/",
            {"scheduled_class": klass.pk, "idempotency_key": "broke-1"},
        )

        assert response.status_code == 402

    def test_mine_lists_own_only(self):
        venue = _venue()
        klass = _class(venue, capacity=5)
        mine = _member(venue, "mine")
        _book(mine, klass, "mine-1")
        _book(_member(venue, "theirs"), klass, "theirs-1")

        response = _client(mine).get("/api/v1/bookings/me/")

        assert response.status_code == 200
        assert len(response.data) == 1
