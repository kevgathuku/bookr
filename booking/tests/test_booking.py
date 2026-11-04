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
    PlanFactory,
    PlanMembershipFactory,
    UserFactory,
    api_client,
    make_member,
    make_session,
    make_venue,
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


class TestBookingModel:
    def test_str(self):
        venue = make_venue("str")
        member = make_member("str-member", venue)
        session = make_session(venue)
        booking = book_session(session=session, member=member)

        assert str(booking) == f"{member} → {session} (booked)"

    def test_clean_rejects_foreign_membership(self):
        venue = make_venue("foreign")
        member = make_member("foreign-member", venue)
        other = make_member("other-member", venue)
        session = make_session(venue)
        booking = book_session(session=session, member=member)
        booking.membership = other.plan_memberships.get()

        with pytest.raises(ValidationError):
            booking.clean()

    def test_clean_rejects_cross_org_plan(self):
        venue = make_venue("home")
        away = make_venue("away")
        member = make_member("away-member", away)
        session = make_session(venue)
        membership = member.plan_memberships.get()
        booking = Booking(
            session=session, member=member, membership=membership, credits_spent=0
        )

        with pytest.raises(ValidationError):
            booking.clean()

    def test_clean_accepts_matching_rows(self):
        venue = make_venue("match")
        member = make_member("match-member", venue)
        session = make_session(venue)
        booking = book_session(session=session, member=member)

        booking.clean()

    def test_create_with_foreign_membership_raises(self):
        venue = make_venue("foreign-save")
        member = make_member("foreign-saver", venue)
        other = make_member("other-saver", venue)
        session = make_session(venue)

        with pytest.raises(ValidationError):
            Booking.objects.create(
                session=session,
                member=member,
                membership=other.plan_memberships.get(),
                credits_spent=0,
            )

    def test_create_with_cross_org_plan_raises(self):
        venue = make_venue("home-save")
        away = make_venue("away-save")
        member = make_member("away-saver", away)
        session = make_session(venue)

        with pytest.raises(ValidationError):
            Booking.objects.create(
                session=session,
                member=member,
                membership=member.plan_memberships.get(),
                credits_spent=0,
            )

    def test_hold_on_non_held_status_rejected_at_db(self):
        venue = make_venue("hold-db")
        member = make_member("hold-db-member", venue)
        session = make_session(venue)
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
        venue = make_venue("downtown")
        session = make_session(venue, capacity=2)

        first = book_session(session=session, member=make_member("m1", venue))
        second = book_session(session=session, member=make_member("m2", venue))

        assert first.status == Booking.Status.BOOKED
        assert second.status == Booking.Status.BOOKED
        assert first.credits_spent == 1

    def test_full_raises_seat_full_without_row(self):
        venue = make_venue("full")
        session = make_session(venue, capacity=1)
        book_session(session=session, member=make_member("m1", venue))

        with pytest.raises(SeatFull):
            book_session(session=session, member=make_member("m2", venue))

        assert session.bookings.count() == 1

    def test_same_member_twice_raises_duplicate(self):
        venue = make_venue("dup")
        session = make_session(venue)
        member = make_member("m1", venue)
        book_session(session=session, member=member)

        with pytest.raises(DuplicateBooking):
            book_session(session=session, member=member)

        assert session.bookings.count() == 1

    def test_rebook_after_cancel_allowed(self):
        venue = make_venue("rebook")
        session = make_session(venue, capacity=1)
        member = make_member("m1", venue)
        booking = book_session(session=session, member=member)
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])

        # Cancelled rows leave the partial unique: seat and slot both free.
        rebook = book_session(session=session, member=member)

        assert rebook.status == Booking.Status.BOOKED

    def test_monthly_books_free_without_balance(self):
        venue = make_venue("monthly")
        session = make_session(venue, price=2)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "m1", org_wide=True)
        with_monthly_plan(member, venue)

        booking = book_session(session=session, member=member)

        assert booking.status == Booking.Status.BOOKED
        assert booking.credits_spent == 0
        membership = member.plan_memberships.get()
        assert membership.credits_remaining is None

    def test_monthly_preferred_over_pack(self):
        venue = make_venue("prefer")
        session = make_session(venue, price=2)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "m1", org_wide=True)
        with_monthly_plan(member, venue)
        pack = PlanFactory(organization=venue.organization, name="m1-pack")
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
        venue = make_venue("oldest")
        session = make_session(venue, price=1)
        member = make_member("m1", venue)
        old_pack = PlanFactory(organization=venue.organization, name="old-pack")
        PlanMembershipFactory(
            user=member,
            plan=old_pack,
            credits_remaining=5,
            starts_on=timezone.now().date() - timedelta(days=20),
        )

        booking = book_session(session=session, member=member)

        assert booking.membership.plan_id == old_pack.pk

    def test_expired_plan_rejected(self):
        venue = make_venue("expired")
        session = make_session(venue)
        member = _user_expired(venue)

        with pytest.raises(CreditInsufficient):
            book_session(session=session, member=member)

        assert session.bookings.count() == 0

    def test_short_balance_rejected_without_row(self):
        venue = make_venue("broke")
        session = make_session(venue, price=2)
        member = make_member("m1", venue, credits=1)

        with pytest.raises(CreditInsufficient):
            book_session(session=session, member=member)

        assert session.bookings.count() == 0

    def test_started_session_rejected(self):
        venue = make_venue("started")
        session = make_session(venue)
        session.starts_at = timezone.now() - timedelta(minutes=5)
        session.save(update_fields=["starts_at"])

        with pytest.raises(ValidationError):
            book_session(session=session, member=make_member("m1", venue))

    def test_cancelled_session_rejected(self):
        venue = make_venue("cancelled")
        session = make_session(venue)
        session.cancelled_at = timezone.now()
        session.save(update_fields=["cancelled_at"])
        member = make_member("m1", venue)

        with pytest.raises(ValidationError):
            book_session(session=session, member=member)

    def test_foreign_membership_rejected(self):
        venue = make_venue("foreign")
        session = make_session(venue)
        member = make_member("m1", venue)
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
        venue = make_venue("race")
        session = make_session(venue, capacity=1)
        members = [make_member(f"racer-{i}", venue) for i in range(20)]
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
        venue = make_venue("double-submit")
        session = make_session(venue, capacity=2)
        member = make_member("double", venue, credits=10)
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
    def test_post_books_and_debits(self):
        venue = make_venue("api-book")
        session = make_session(venue, price=2)
        member = make_member("m1", venue, credits=5)

        response = api_client(member, venue_slug=venue.slug).post(
            "/api/v1/bookings/", {"session": session.pk}
        )

        assert response.status_code == 201
        assert response.data["status"] == "booked"
        assert response.data["credits_spent"] == 2
        member.plan_memberships.get().refresh_from_db()

    def test_post_full_is_409(self):
        venue = make_venue("api-full")
        session = make_session(venue, capacity=1)
        book_session(session=session, member=make_member("m1", venue))

        response = api_client(make_member("m2", venue), venue_slug=venue.slug).post(
            "/api/v1/bookings/", {"session": session.pk}
        )

        assert response.status_code == 409

    def test_post_without_plan_is_402(self):
        # Venue access (org-wide role) but nothing to pay with.
        venue = make_venue("api-broke")
        session = make_session(venue)
        member = user_with_role(venue, OrgRole.Role.MEMBER, "broke", org_wide=True)

        response = api_client(member, venue_slug=venue.slug).post(
            "/api/v1/bookings/", {"session": session.pk}
        )

        assert response.status_code == 402

    def test_mine_lists_only_own(self):
        venue = make_venue("api-mine")
        session = make_session(venue)
        member = make_member("m1", venue)
        booking = book_session(session=session, member=member)

        response = api_client(member, venue_slug=venue.slug).get(
            "/api/v1/bookings/me/?mine=true"
        )

        assert response.status_code == 200
        assert [b["id"] for b in response.data] == [booking.pk]

    def test_roster_lists_venue_sessions(self):
        from organizations.models import OrgRole

        venue = make_venue("api-roster")
        session = make_session(venue)
        member = make_member("m1", venue)
        booking = book_session(session=session, member=member)
        staff = user_with_role(venue, OrgRole.Role.MANAGER, username="roster-staff")
        day = (timezone.now() + timedelta(days=1)).date().isoformat()

        response = api_client(staff, venue_slug=venue.slug).get(
            f"/api/v1/bookings/roster/?date={day}"
        )

        assert response.status_code == 200
        assert response.data[0]["member"] == member.username
        assert response.data[0]["class_title"] == "Spin"
        assert response.data[0]["checked_in_at"] is None
        assert response.data[0]["id"] == booking.pk

    def test_roster_member_403(self):
        venue = make_venue("api-roster-403")
        member = make_member("m1", venue)

        response = api_client(member, venue_slug=venue.slug).get(
            "/api/v1/bookings/roster/"
        )

        assert response.status_code == 403
