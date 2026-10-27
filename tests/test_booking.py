from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.utils import timezone

from booking.errors import CreditInsufficient, DuplicateBooking, SeatFull
from booking.models import Booking
from booking.services import book_seat
from organizations.models import Organization, Venue
from scheduling.models import ClassType, Room, ScheduledClass

pytestmark = pytest.mark.django_db

#  book_seat service seam
#  - Confirmed while seats remain; SeatFull when full (no row written).
#  - waitlist=True turns a full class into a waitlisted booking.
#  - Same idempotency key twice → the one booking (no duplicate row).
#  - Same member twice while active → DuplicateBooking.
#  - Cancelled bookings release both seat and member slot (rebook allowed).
#  - Credit hook: called inside the transaction; CreditInsufficient aborts
#    with no booking written (real ledger wires in with the passes ticket).
#  - Booking venue always equals the class venue (derived, not passed).
#
#  Concurrency seam (transactional marker: threads need committed setup)
#  - 20 threads, 1 seat → exactly 1 confirmed, 19 SeatFull.


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    return Venue.objects.create(organization=org, slug=slug, name=slug.title())


def _user(username):
    return get_user_model().objects.create_user(username=username)


def _class(venue, capacity=2, **overrides):
    start = timezone.now() + timedelta(days=1)
    defaults = {
        "venue": venue,
        "class_type": ClassType.objects.get_or_create(
            venue=venue,
            name="Spin",
            defaults={"duration_min": 45, "capacity_default": 20},
        )[0],
        "room": Room.objects.get_or_create(
            venue=venue, name="Studio A", defaults={"capacity": capacity}
        )[0],
        "teacher": _user(f"teacher-{venue.slug}"),
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
    }
    defaults.update(overrides)
    return ScheduledClass.objects.create(**defaults)


class TestBookSeat:
    def test_confirmed_while_seats_remain(self):
        venue = _venue()
        klass = _class(venue, capacity=2)

        b1 = book_seat(_user("m1"), klass, idempotency_key="k1")
        b2 = book_seat(_user("m2"), klass, idempotency_key="k2")

        assert b1.status == "confirmed"
        assert b2.status == "confirmed"
        assert b1.venue == venue == b2.venue  # derived from class, never passed

    def test_full_raises_seat_full_without_row(self):
        venue = _venue()
        klass = _class(venue, capacity=1)
        book_seat(_user("m1"), klass, idempotency_key="k1")

        with pytest.raises(SeatFull):
            book_seat(_user("m2"), klass, idempotency_key="k2")

        assert klass.bookings.count() == 1

    def test_full_with_waitlist_flag_waitlists(self):
        venue = _venue()
        klass = _class(venue, capacity=1)
        book_seat(_user("m1"), klass, idempotency_key="k1")

        booking = book_seat(_user("m2"), klass, idempotency_key="k2", waitlist=True)

        assert booking.status == "waitlisted"

    def test_same_key_twice_returns_one_booking(self):
        venue = _venue()
        klass = _class(venue)
        member = _user("m1")

        first = book_seat(member, klass, idempotency_key="same")
        second = book_seat(member, klass, idempotency_key="same")

        assert first.pk == second.pk
        assert klass.bookings.count() == 1

    def test_same_member_twice_raises_duplicate(self):
        venue = _venue()
        klass = _class(venue)
        member = _user("m1")
        book_seat(member, klass, idempotency_key="k1")

        with pytest.raises(DuplicateBooking):
            book_seat(member, klass, idempotency_key="k2")

    def test_rebook_after_cancel_allowed(self):
        venue = _venue()
        klass = _class(venue, capacity=1)
        member = _user("m1")
        booking = book_seat(member, klass, idempotency_key="k1")
        booking.status = "cancelled"
        booking.save()

        # Cancelled rows leave the partial unique → seat and slot both free.
        rebook = book_seat(member, klass, idempotency_key="k2")

        assert rebook.status == "confirmed"

    def test_credit_hook_called_and_insufficient_aborts(self):
        venue = _venue()
        klass = _class(venue)
        calls = []

        def spend():
            calls.append(True)
            raise CreditInsufficient("no credits left")

        with pytest.raises(CreditInsufficient):
            book_seat(_user("m1"), klass, idempotency_key="k1", spend_credit=spend)

        assert calls == [True]
        assert klass.bookings.count() == 0

    def test_idempotency_key_unique_at_db(self):
        venue = _venue()
        klass = _class(venue)
        member = _user("m1")
        Booking.objects.create(
            venue=venue, member=member, scheduled_class=klass, idempotency_key="dup"
        )

        # Service-independent: the column itself refuses a second row.
        with pytest.raises(IntegrityError):
            Booking.objects.create(
                venue=venue,
                member=_user("m2"),
                scheduled_class=klass,
                idempotency_key="dup",
            )


@pytest.mark.django_db(transaction=True)
class TestLastSeatRace:
    def test_twenty_threads_one_seat_yields_one_confirmed(self):
        venue = _venue(slug="race")
        klass = _class(venue, capacity=1)
        members = [_user(f"racer-{i}") for i in range(20)]
        outcomes = []

        def attempt(i):
            try:
                booking = book_seat(members[i], klass, idempotency_key=f"race-{i}")
                return booking.status
            except SeatFull:
                return "full"
            finally:
                # Threads hold their connection open; release it so the
                # test database can tear down.
                connection.close()

        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(attempt, range(20)))

        assert outcomes.count("confirmed") == 1
        assert outcomes.count("full") == 19
        assert klass.bookings.filter(status="confirmed").count() == 1
