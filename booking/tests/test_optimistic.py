"""Optimistic booking transitions (bookr-huh).

Stale writers lose: the Booking.version check turns an overwrite into
AlreadyCancelled. Deterministic (no threads), so these run on every
backend, including SQLite.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from booking._core import bump_session, transition_booking
from booking.cancellations import cancel_booking, cancel_session
from booking.errors import AlreadyCancelled, ConcurrentWrite, NotHeld, SeatFull
from booking.models import Booking, CancellationRecord
from booking.services import (
    _raise_for_confirm_conflict,
    _seat_head,
    book_session,
    confirm_booking,
    promote_next,
)
from common.ids import BookingId, SessionId
from organizations.models import OrgRole
from scheduling.models import ClassSession
from tests.factories import book, make_member, make_session, user_with_role

pytestmark = pytest.mark.django_db


class TestOptimisticTransitions:
    def test_stale_cancel_loses_to_first_writer(self, venue):
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        member = make_member("m1", venue, credits=10)
        booking = book(member, session)
        stale = Booking.objects.get(pk=booking.pk)
        cancel_booking(
            booking_id=BookingId(booking.pk),
            actor=member,
            now=timezone.now(),
            reason="first",
        )

        with pytest.raises(AlreadyCancelled):
            transition_booking(stale, status=Booking.Status.CANCELLED)

    def test_transition_writes_and_bumps(self, venue):
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        member = make_member("m1", venue, credits=10)
        booking = book(member, session)

        transition_booking(booking, status=Booking.Status.NO_SHOW)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.NO_SHOW
        assert booking.version == 2

    def test_lost_confirm_race_maps_to_fresh_status(self, venue):
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        member = make_member("m1", venue, credits=10)
        booking = book(member, session, price=0)
        booking.status = Booking.Status.WAITLISTED
        booking.save(update_fields=["status"])
        promote_next(session)
        taken = Booking.objects.get(pk=booking.pk)
        gone = Booking.objects.get(pk=booking.pk)
        confirm_booking(booking_id=BookingId(booking.pk), actor=member)

        with pytest.raises(NotHeld):
            _raise_for_confirm_conflict(taken)

        Booking.objects.filter(pk=taken.pk).update(status=Booking.Status.CANCELLED)
        with pytest.raises(AlreadyCancelled):
            _raise_for_confirm_conflict(gone)


class TestSessionBump:
    """Occupancy serialization without row locks: every seat-taking unit
    bumps the session version, so a stale count retries instead of
    overfilling. Deterministic, backend-independent."""

    def test_stale_bump_loses(self, venue):
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        stale = ClassSession.objects.get(pk=session.pk)
        book(make_member("other", venue, credits=10), session)

        with pytest.raises(ConcurrentWrite):
            bump_session(stale)

    def test_book_with_stale_snapshot_retries(self, venue):
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        stale = ClassSession.objects.get(pk=session.pk)
        book(make_member("other", venue, credits=10), session)

        booking = book_session(session=stale, member=make_member("m1", venue))

        assert booking.status == Booking.Status.BOOKED
        assert booking.version == 1

    def test_full_session_with_stale_snapshot_queues(self, venue):
        session = make_session(
            venue, starts_at=timezone.now() + timedelta(hours=48), capacity=1
        )
        book(make_member("first", venue, credits=10), session)
        stale = ClassSession.objects.get(pk=session.pk)

        queued = book_session(
            session=stale, member=make_member("m2", venue), waitlist=True
        )

        assert queued.status == Booking.Status.WAITLISTED
        with pytest.raises(SeatFull):
            book_session(session=stale, member=make_member("m3", venue))

    def test_seat_head_conflict_raises(self, venue):
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        member = make_member("m1", venue, credits=10)
        booking = book(member, session, price=0)
        booking.status = Booking.Status.WAITLISTED
        booking.save(update_fields=["status"])
        stale_head = Booking.objects.get(pk=booking.pk)
        promote_next(session)

        with pytest.raises(AlreadyCancelled):
            _seat_head(locked=session, head=stale_head, moment=timezone.now())


class TestWaitlistSnapshot:
    def test_stale_join_after_session_cancel_refuses(self, venue):
        from django.core.exceptions import ValidationError

        session = make_session(
            venue, starts_at=timezone.now() + timedelta(hours=48), capacity=1
        )
        book(make_member("first", venue, credits=10), session)
        stale = ClassSession.objects.get(pk=session.pk)
        desk = user_with_role(
            venue, OrgRole.Role.FRONTDESK, "desk", org_wide=True, staff=True
        )
        cancel_session(session_id=SessionId(session.pk), actor=desk, reason="storm")

        with pytest.raises(ValidationError, match="cancelled"):
            book_session(session=stale, member=make_member("m2", venue), waitlist=True)

        assert not Booking.objects.filter(
            session=session, status=Booking.Status.WAITLISTED
        ).exists()


class TestSessionSweepConflict:
    """The session sweep only skips rows a terminal transition won. A
    still-live row (a confirm landed first) is re-claimed and refunded."""

    def _held_booking(self, venue, member):
        session = make_session(
            venue, starts_at=timezone.now() + timedelta(hours=48), capacity=1
        )
        filler = make_member("filler", venue, credits=10)
        seated = book(filler, session)
        booking = book_session(session=session, member=member, waitlist=True)
        cancel_booking(
            booking_id=BookingId(seated.pk),
            actor=filler,
            now=timezone.now(),
            reason="frees the seat",
        )
        promote_next(session)
        return session, Booking.objects.get(pk=booking.pk)

    def test_sweep_claims_confirm_won_row(self, venue):
        from booking.cancellations import _cancel_one_for_session

        member = make_member("m1", venue, credits=10)
        session, stale = self._held_booking(venue, member)
        # The sweep read the HELD row, then the confirm committed first.
        confirm_booking(booking_id=BookingId(stale.pk), actor=member)
        before = member.plan_memberships.get().credits_remaining

        record = _cancel_one_for_session(
            booking=stale,
            session=session,
            venue=venue,
            organization=venue.organization,
            actor=member,
        )

        assert record is not None
        assert (
            record.cause == CancellationRecord.Cause.SESSION_CANCELLED
        )
        stale.refresh_from_db()
        assert stale.status == Booking.Status.CANCELLED
        member.plan_memberships.get().refresh_from_db()
        assert (
            member.plan_memberships.get().credits_remaining
            == before + record.credits_refunded
        )
        assert record.credits_refunded > 0

    def test_sweep_skips_member_cancelled_row(self, venue):
        from booking.cancellations import _cancel_one_for_session

        member = make_member("m1", venue, credits=10)
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=48))
        booking = book(member, session)
        stale = Booking.objects.get(pk=booking.pk)
        cancel_booking(
            booking_id=BookingId(booking.pk),
            actor=member,
            now=timezone.now(),
            reason="mine",
        )

        assert (
            _cancel_one_for_session(
                booking=stale,
                session=session,
                venue=venue,
                organization=venue.organization,
                actor=member,
            )
            is None
        )
