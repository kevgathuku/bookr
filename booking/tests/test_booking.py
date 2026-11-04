from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.utils import timezone

from booking.errors import CreditInsufficient, DuplicateBooking, SeatFull
from booking.models import Booking
from booking.services import book_session
from organizations.models import OrgRole
from passes.models import CreditLedger, PlanType
from tests.factories import (  # noqa: WPS235
    ClassOfferingFactory,
    ClassSessionFactory,
    PlanFactory,
    PlanMembershipFactory,
    UserFactory,
    VenueFactory,
    user_with_role,
    with_monthly_plan,
)

pytestmark = pytest.mark.django_db

#  book_session service seam
#  - Confirmed while seats remain; SeatFull when full (no row written).
#  - Same member + session twice while active → DuplicateBooking, no row.
#  - Cancelled rows leave the partial unique → seat and slot both free.
#  - Payer selection: monthly first, then oldest valid credit pack.
#  - Monthly books free: no balance moved, stamped zero.
#  - Expired plan or short balance → CreditInsufficient, nothing written.
#  - Started or cancelled sessions refuse with ValidationError.
#  - Retries are safe: no double booking, no double spend.
#
#  Concurrency seam (transactional marker: threads need committed setup)
#  - 20 threads, 1 seat → exactly 1 booked, 19 SeatFull.


def _venue(slug):
    return VenueFactory(slug=slug, name=slug.title())


def _pack(venue, name, duration_days=30):
    return PlanFactory(
        organization=venue.organization,
        name=name,
        plan_type=PlanType.CREDIT_PACK,
        duration_days=duration_days,
    )


def _member(username, venue, credits=10, plan=None):
    # Venue access rides on the org-wide member role; the plan only pays.
    user = user_with_role(venue, OrgRole.Role.MEMBER, username, org_wide=True)
    plan = plan or _pack(venue, f"{username}-pack")
    PlanMembershipFactory(
        user=user,
        plan=plan,
        credits_remaining=credits,
        starts_on=timezone.now().date(),
    )
    return user


def _session(venue, price=1, capacity=2, teacher=None):
    teacher = teacher or UserFactory(username=f"teacher-{venue.slug}")
    offering = ClassOfferingFactory(
        venue=venue, teacher=teacher, title="Spin", credit_cost=price
    )
    return ClassSessionFactory(
        offering=offering,
        starts_at=timezone.now() + timedelta(days=1),
        capacity=capacity,
    )


class TestBookingModel:
    def test_str(self):
        venue = _venue("str")
        member = _member("str-member", venue)
        session = _session(venue)
        booking = book_session(session=session, member=member)

        assert str(booking) == f"{member} → {session} (booked)"

    def test_clean_rejects_foreign_membership(self):
        venue = _venue("foreign")
        member = _member("foreign-member", venue)
        other = _member("other-member", venue)
        session = _session(venue)
        booking = book_session(session=session, member=member)
        booking.membership = other.plan_memberships.get()

        with pytest.raises(ValidationError):
            booking.clean()

    def test_clean_rejects_cross_org_plan(self):
        venue = _venue("home")
        away = _venue("away")
        member = _member("away-member", away)
        session = _session(venue)
        membership = member.plan_memberships.get()
        booking = Booking(
            session=session, member=member, membership=membership, credits_spent=0
        )

        with pytest.raises(ValidationError):
            booking.clean()

    def test_clean_accepts_matching_rows(self):
        venue = _venue("match")
        member = _member("match-member", venue)
        session = _session(venue)
        booking = book_session(session=session, member=member)

        booking.clean()

    def test_create_with_foreign_membership_raises(self):
        venue = _venue("foreign-save")
        member = _member("foreign-saver", venue)
        other = _member("other-saver", venue)
        session = _session(venue)

        with pytest.raises(ValidationError):
            Booking.objects.create(
                session=session,
                member=member,
                membership=other.plan_memberships.get(),
                credits_spent=0,
            )

    def test_create_with_cross_org_plan_raises(self):
        venue = _venue("home-save")
        away = _venue("away-save")
        member = _member("away-saver", away)
        session = _session(venue)

        with pytest.raises(ValidationError):
            Booking.objects.create(
                session=session,
                member=member,
                membership=member.plan_memberships.get(),
                credits_spent=0,
            )

    def test_hold_on_non_held_status_rejected_at_db(self):
        venue = _venue("hold-db")
        member = _member("hold-db-member", venue)
        session = _session(venue)
        membership = member.plan_memberships.get()

        with pytest.raises(IntegrityError):
            Booking.objects.create(
                session=session,
                member=member,
                membership=membership,
                credits_spent=0,
                status="booked",
                hold_expires_at=timezone.now() + timedelta(hours=1),
            )


class TestBookSession:
    def test_confirmed_while_seats_remain(self):
        venue = _venue("downtown")
        session = _session(venue, capacity=2)

        first = book_session(session=session, member=_member("m1", venue))
        second = book_session(session=session, member=_member("m2", venue))

        assert first.status == Booking.Status.BOOKED
        assert second.status == Booking.Status.BOOKED
        assert first.credits_spent == 1

    def test_full_raises_seat_full_without_row(self):
        venue = _venue("full")
        session = _session(venue, capacity=1)
        book_session(session=session, member=_member("m1", venue))

        with pytest.raises(SeatFull):
            book_session(session=session, member=_member("m2", venue))

        assert session.bookings.count() == 1

    def test_same_member_twice_raises_duplicate(self):
        venue = _venue("dup")
        session = _session(venue)
        member = _member("m1", venue)
        book_session(session=session, member=member)

        with pytest.raises(DuplicateBooking):
            book_session(session=session, member=member)

        assert session.bookings.count() == 1

    def test_rebook_after_cancel_allowed(self):
        venue = _venue("rebook")
        session = _session(venue, capacity=1)
        member = _member("m1", venue)
        booking = book_session(session=session, member=member)
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])

        # Cancelled rows leave the partial unique: seat and slot both free.
        rebook = book_session(session=session, member=member)

        assert rebook.status == Booking.Status.BOOKED

    def test_monthly_books_free_without_balance(self):
        venue = _venue("monthly")
        session = _session(venue, price=2)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "m1", org_wide=True)
        with_monthly_plan(member, venue)

        booking = book_session(session=session, member=member)

        assert booking.status == Booking.Status.BOOKED
        assert booking.credits_spent == 0
        membership = member.plan_memberships.get()
        assert membership.credits_remaining is None

    def test_monthly_preferred_over_pack(self):
        venue = _venue("prefer")
        session = _session(venue, price=2)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "m1", org_wide=True)
        with_monthly_plan(member, venue)
        pack = _pack(venue, "m1-pack")
        PlanMembershipFactory(
            user=member,
            plan=pack,
            credits_remaining=10,
            starts_on=timezone.now().date(),
        )

        booking = book_session(session=session, member=member)

        assert booking.membership.plan.plan_type == PlanType.MONTHLY
        pack_membership = member.plan_memberships.get(plan=pack)
        assert pack_membership.credits_remaining == 10

    def test_oldest_pack_first(self):
        venue = _venue("oldest")
        session = _session(venue, price=1)
        member = _member("m1", venue)
        old_pack = _pack(venue, "old-pack")
        PlanMembershipFactory(
            user=member,
            plan=old_pack,
            credits_remaining=5,
            starts_on=timezone.now().date() - timedelta(days=20),
        )

        booking = book_session(session=session, member=member)

        assert booking.membership.plan_id == old_pack.pk

    def test_expired_plan_rejected(self):
        venue = _venue("expired")
        session = _session(venue)
        member = _user_expired(venue)

        with pytest.raises(CreditInsufficient):
            book_session(session=session, member=member)

        assert session.bookings.count() == 0

    def test_short_balance_rejected_without_row(self):
        venue = _venue("broke")
        session = _session(venue, price=2)
        member = _member("m1", venue, credits=1)

        with pytest.raises(CreditInsufficient):
            book_session(session=session, member=member)

        assert session.bookings.count() == 0

    def test_started_session_rejected(self):
        venue = _venue("started")
        session = _session(venue)
        session.starts_at = timezone.now() - timedelta(minutes=5)
        session.save(update_fields=["starts_at"])

        with pytest.raises(ValidationError):
            book_session(session=session, member=_member("m1", venue))

    def test_cancelled_session_rejected(self):
        venue = _venue("cancelled")
        session = _session(venue)
        session.cancelled_at = timezone.now()
        session.save(update_fields=["cancelled_at"])
        member = _member("m1", venue)

        with pytest.raises(ValidationError):
            book_session(session=session, member=member)

    def test_foreign_membership_rejected(self):
        venue = _venue("foreign")
        session = _session(venue)
        member = _member("m1", venue)
        stranger = UserFactory(username="stranger")
        stranger_membership = PlanMembershipFactory(user=stranger)

        with pytest.raises(ValidationError):
            book_session(session=session, member=member, membership=stranger_membership)


def _user_expired(venue):
    user = UserFactory(username="expired")
    plan = PlanFactory(
        organization=venue.organization,
        name="expired-pack",
        plan_type=PlanType.CREDIT_PACK,
        duration_days=30,
    )
    PlanMembershipFactory(
        user=user,
        plan=plan,
        credits_remaining=10,
        starts_on=timezone.now().date() - timedelta(days=60),
        valid_until=timezone.now().date() - timedelta(days=30),
    )
    return user


@pytest.mark.django_db(transaction=True)
class TestLastSeatRace:
    def test_twenty_threads_one_seat_yields_one_booked(self):
        venue = _venue("race")
        session = _session(venue, capacity=1)
        members = [_member(f"racer-{i}", venue) for i in range(20)]
        outcomes = []

        def attempt(i):
            try:
                booking = book_session(session=session, member=members[i])
                return booking.status
            except SeatFull:
                return "full"
            finally:
                # Threads hold their connection open; release it so the
                # test database can tear down.
                connection.close()

        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(attempt, range(20)))

        assert outcomes.count(Booking.Status.BOOKED) == 1
        assert outcomes.count("full") == 19
        assert session.bookings.filter(status=Booking.Status.BOOKED).count() == 1


@pytest.mark.django_db(transaction=True)
class TestDoubleSubmitRace:
    def test_same_member_double_submit_charges_once(self):
        venue = _venue("double-submit")
        session = _session(venue, capacity=2)
        member = _member("double", venue, credits=10)
        outcomes = []
        gate = Barrier(2)

        def attempt(_i):
            gate.wait(timeout=10)
            try:
                booking = book_session(session=session, member=member)
                return booking.status
            except DuplicateBooking:
                return "duplicate"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))

        assert outcomes.count(Booking.Status.BOOKED) == 1
        assert outcomes.count("duplicate") == 1
        assert (
            CreditLedger.objects.filter(
                booking__session=session,
                reason=CreditLedger.Reason.BOOKING,
            ).count()
            == 1
        )
        member.plan_memberships.get().refresh_from_db()
        assert member.plan_memberships.get().credits_remaining == 9


class TestBookingApi:
    def _client(self, member, venue):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=member)
        client.defaults["HTTP_X_VENUE_SLUG"] = venue.slug
        return client

    def test_post_books_and_debits(self):
        venue = _venue("api-book")
        session = _session(venue, price=2)
        member = _member("m1", venue, credits=5)

        response = self._client(member, venue).post(
            "/api/v1/bookings/", {"session": session.pk}
        )

        assert response.status_code == 201
        assert response.data["status"] == "booked"
        assert response.data["credits_spent"] == 2
        member.plan_memberships.get().refresh_from_db()

    def test_post_full_is_409(self):
        venue = _venue("api-full")
        session = _session(venue, capacity=1)
        book_session(session=session, member=_member("m1", venue))

        response = self._client(_member("m2", venue), venue).post(
            "/api/v1/bookings/", {"session": session.pk}
        )

        assert response.status_code == 409

    def test_post_without_plan_is_402(self):
        # Venue access (org-wide role) but nothing to pay with.
        venue = _venue("api-broke")
        session = _session(venue)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "broke", org_wide=True)

        response = self._client(member, venue).post(
            "/api/v1/bookings/", {"session": session.pk}
        )

        assert response.status_code == 402

    def test_mine_lists_only_own(self):
        venue = _venue("api-mine")
        session = _session(venue)
        member = _member("m1", venue)
        booking = book_session(session=session, member=member)

        response = self._client(member, venue).get("/api/v1/bookings/me/?mine=true")

        assert response.status_code == 200
        assert [b["id"] for b in response.data] == [booking.pk]

    def test_roster_lists_venue_sessions(self):
        from organizations.models import OrgRole
        from tests.factories import user_with_role

        venue = _venue("api-roster")
        session = _session(venue)
        member = _member("m1", venue)
        booking = book_session(session=session, member=member)
        staff = user_with_role(venue, OrgRole.Role.MANAGER, username="roster-staff")
        day = (timezone.now() + timedelta(days=1)).date().isoformat()

        response = self._client(staff, venue).get(
            f"/api/v1/bookings/roster/?date={day}"
        )

        assert response.status_code == 200
        assert response.data[0]["member"] == member.username
        assert response.data[0]["class_title"] == "Spin"
        assert response.data[0]["checked_in_at"] is None
        assert response.data[0]["id"] == booking.pk

    def test_roster_member_403(self):
        venue = _venue("api-roster-403")
        member = _member("m1", venue)

        response = self._client(member, venue).get("/api/v1/bookings/roster/")

        assert response.status_code == 403
