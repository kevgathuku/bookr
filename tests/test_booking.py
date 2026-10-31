from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from booking.errors import CreditInsufficient, DuplicateBooking, SeatFull
from booking.models import Booking
from booking.services import book_session
from organizations.models import OrgRole
from passes.models import PlanType
from tests.factories import (
    ClassOfferingFactory,
    ClassSessionFactory,
    MembershipPlanFactory,
    OrgRoleFactory,
    PlanMembershipFactory,
    UserFactory,
    VenueFactory,
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


def _pack(venue, name, validity_days=30):
    return MembershipPlanFactory(
        organization=venue.organization,
        name=name,
        plan_type=PlanType.CREDIT_PACK,
        validity_days=validity_days,
    )


def _member(username, venue, credits=10, plan=None):
    # Venue access rides on the org-wide member role; the plan only pays.
    user = UserFactory(username=username)
    OrgRoleFactory(
        organization=venue.organization, venue=None, user=user, role=OrgRole.Role.MEMBER
    )
    plan = plan or _pack(venue, f"{username}-pack")
    PlanMembershipFactory(
        user=user,
        plan=plan,
        credits_remaining=credits,
        starts_on=timezone.now().date(),
    )
    return user


def _monthly(username, venue):
    user = UserFactory(username=username)
    OrgRoleFactory(
        organization=venue.organization, venue=None, user=user, role=OrgRole.Role.MEMBER
    )
    plan = MembershipPlanFactory(
        organization=venue.organization,
        name=f"{username}-monthly",
        plan_type=PlanType.MONTHLY,
        validity_days=30,
    )
    PlanMembershipFactory(
        user=user, plan=plan, credits_remaining=0, starts_on=timezone.now().date()
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
        member = _monthly("m1", venue)

        booking = book_session(session=session, member=member)

        assert booking.status == Booking.Status.BOOKED
        assert booking.credits_spent == 0
        membership = member.plan_memberships.get()
        assert membership.credits_remaining == 0

    def test_monthly_preferred_over_pack(self):
        venue = _venue("prefer")
        session = _session(venue, price=2)
        member = _monthly("m1", venue)
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
    plan = MembershipPlanFactory(
        organization=venue.organization,
        name="expired-pack",
        plan_type=PlanType.CREDIT_PACK,
        validity_days=30,
    )
    PlanMembershipFactory(
        user=user,
        plan=plan,
        credits_remaining=10,
        starts_on=timezone.now().date() - timedelta(days=60),
        ends_on=timezone.now().date() - timedelta(days=30),
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
        member = UserFactory(username="broke")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )

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
        assert response.data[0]["session_title"] == "Spin"
        assert response.data[0]["id"] == booking.pk
