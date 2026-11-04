"""Waitlist seam (bookr-0sr.9): queue on full GROUP sessions, FIFO promote.

Slice 1 — creation:
- Full GROUP session + waitlist=True → WAITLISTED, no seat, no spend.
- Same call without the flag → SeatFull, nothing written.
- Private sessions refuse the queue (SeatFull either way, no row).
- Re-joining while queued → DuplicateBooking.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from booking.cancellations import cancel_booking, cancel_session, mark_no_show
from booking.errors import (
    AlreadyCancelled,
    CreditInsufficient,
    DuplicateBooking,
    NotHeld,
    SeatFull,
    SessionStarted,
)
from booking.models import Booking, CancellationPolicy, CancellationRecord
from booking.services import (
    HOLD_WINDOW_MINUTES,
    _lapse_hold,
    book_session,
    confirm_booking,
    promote_next,
    sweep_expired_holds,
)
from organizations.models import OrgRole
from passes.models import CreditLedger, Membership, PlanType
from scheduling.models import ClassCategory, ClassSession
from tests.factories import (  # noqa: WPS235
    CancellationPolicyFactory,
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


def _world(category=ClassCategory.GROUP, capacity=1, credits=10):
    venue = VenueFactory(slug="waitlist-gym", name="Waitlist Gym")
    teacher = UserFactory(username="waitlist-teacher")
    offering = ClassOfferingFactory(
        venue=venue, teacher=teacher, title="Spin", category=category
    )
    session = ClassSessionFactory(
        offering=offering,
        starts_at=timezone.now() + timedelta(days=1),
        capacity=capacity,
    )
    plan = PlanFactory(
        organization=venue.organization,
        name="wait-pack",
        plan_type=PlanType.CREDIT_PACK,
        duration_days=30,
    )

    def member(username, member_credits=credits):
        user = user_with_role(venue, OrgRole.Role.MEMBER, username, org_wide=True)
        PlanMembershipFactory(
            user=user,
            plan=plan,
            credits_remaining=member_credits,
            starts_on=timezone.now().date(),
        )
        return user

    return session, member


class TestWaitlistCreation:
    def test_full_group_queues_with_no_spend(self):
        session, member = _world(capacity=1)
        seated = member("seated")
        queued = member("queued")
        book_session(session=session, member=seated)

        waiting = book_session(session=session, member=queued, waitlist=True)

        assert waiting.status == Booking.Status.WAITLISTED
        assert waiting.credits_spent == 0
        assert (
            Booking.objects.filter(
                session=session, status=Booking.Status.BOOKED
            ).count()
            == 1
        )

    def test_full_group_without_flag_stays_seat_full(self):
        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))

        with pytest.raises(SeatFull):
            book_session(session=session, member=member("turned-away"))

        assert not Booking.objects.filter(
            session=session, member__username="turned-away"
        ).exists()

    def test_private_session_refuses_the_queue(self):
        session, member = _world(category=ClassCategory.PRIVATE, capacity=1)
        book_session(session=session, member=member("seated"))

        with pytest.raises(SeatFull):
            book_session(session=session, member=member("queued"), waitlist=True)

        assert not Booking.objects.filter(
            session=session, member__username="queued"
        ).exists()

    def test_rejoin_while_queued_is_duplicate(self):
        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        queued = member("queued")
        book_session(session=session, member=queued, waitlist=True)

        with pytest.raises(DuplicateBooking):
            book_session(session=session, member=queued, waitlist=True)


def _fill(session, member, count=1, prefix="seat"):
    booked = []
    for index in range(count):
        booked.append(book_session(session=session, member=member(f"{prefix}{index}")))
    return booked


class TestPromoteNext:
    def _queued_world(self):
        session, member = _world(capacity=1)
        before = timezone.now()
        seated_booking = book_session(session=session, member=member("seated"))
        first = book_session(session=session, member=member("first"), waitlist=True)
        book_session(session=session, member=member("second"), waitlist=True)
        Booking.objects.filter(pk=seated_booking.pk).update(
            status=Booking.Status.CANCELLED
        )
        Booking.objects.filter(pk=first.pk).update(
            created_at=before - timedelta(minutes=5)
        )
        return session, before, first

    def test_fifo_head_promoted(self):
        session, _before, first = self._queued_world()

        promoted = promote_next(session)

        assert promoted is not None
        assert promoted.pk == first.pk
        assert promoted.status == Booking.Status.HELD
        assert (
            Booking.objects.filter(
                session=session, status=Booking.Status.WAITLISTED
            ).count()
            == 1
        )

    def test_promotion_holds_without_spend(self):
        session, before, _first = self._queued_world()

        promoted = promote_next(session)

        assert promoted is not None
        assert promoted.credits_spent == 0
        assert promoted.hold_expires_at is not None
        assert promoted.hold_expires_at - before >= timedelta(
            minutes=HOLD_WINDOW_MINUTES - 1
        )

    def test_promotion_writes_no_ledger(self):
        session, member = _world(capacity=1, credits=10)
        seated = member("seated")
        queued = member("queued")
        opening = Membership.objects.get(user=queued).credits_remaining
        seated_booking = book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        Booking.objects.filter(pk=seated_booking.pk).update(
            status=Booking.Status.CANCELLED
        )

        promote_next(session)

        waiting.refresh_from_db()
        assert waiting.credits_spent == 0
        assert waiting.status == Booking.Status.HELD
        assert Membership.objects.get(user=queued).credits_remaining == opening
        assert not CreditLedger.objects.filter(booking=waiting).exists()

    def test_lapsed_pass_still_promoted_without_spend(self):
        # Promotion never checks passes: the head is seated as Held and
        # confirm collects the 402 when the pass cannot pay.
        session, member = _world(capacity=1)
        seated = book_session(session=session, member=member("seated"))
        queued = member("queued")
        book_session(session=session, member=queued, waitlist=True)
        Booking.objects.filter(pk=seated.pk).update(status=Booking.Status.CANCELLED)
        queued.plan_memberships.update(
            starts_on=timezone.now().date() - timedelta(days=60),
            valid_until=timezone.now().date() - timedelta(days=1),
        )

        promoted = promote_next(session)

        assert promoted is not None
        assert promoted.status == Booking.Status.HELD
        assert promoted.credits_spent == 0

    def test_promote_is_idle_when_full_or_empty(self):
        session, member = _world(capacity=1)
        assert promote_next(session) is None
        book_session(session=session, member=member("seated"))
        assert promote_next(session) is None

    @pytest.mark.django_db(transaction=True)
    def test_promote_is_retry_safe_under_races(self):

        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        book_session(session=session, member=member("queued"), waitlist=True)
        Booking.objects.filter(member__username="seated").update(
            status=Booking.Status.CANCELLED
        )
        connection.close()

        results = []

        def attempt(_):
            try:
                return promote_next(session)
            finally:
                # Threads hold their connection open; release it so the
                # test database can tear down.
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))

        assert sum(result is not None for result in results) == 1
        assert (
            Booking.objects.filter(session=session, status=Booking.Status.HELD).count()
            == 1
        )


class TestSweepExpiredHolds:
    def test_lapsed_hold_releases_unclaimed_and_promotes_next(self):
        session, member = _world(capacity=1, credits=10)
        seated = member("seated")
        queued = member("queued")
        book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        Booking.objects.filter(member=seated).update(status=Booking.Status.CANCELLED)
        promote_next(session)
        opening = Membership.objects.get(user=queued).credits_remaining
        Booking.objects.filter(member=queued).update(
            hold_expires_at=timezone.now() - timedelta(minutes=1)
        )

        swept = sweep_expired_holds()

        assert swept == 1
        assert sweep_expired_holds() == 0
        waiting.refresh_from_db()
        assert (waiting.status, waiting.hold_expires_at) == (
            Booking.Status.CANCELLED,
            None,
        )
        assert Membership.objects.get(user=queued).credits_remaining == opening
        assert not CreditLedger.objects.filter(booking=waiting).exists()
        record = CancellationRecord.objects.get(booking=waiting)
        assert (record.cause, record.enforcement_applied, record.credits_refunded) == (
            CancellationRecord.Cause.UNCLAIMED,
            CancellationPolicy.Enforcement.NONE,
            0,
        )

    def test_sweep_releases_hold_expiring_exactly_on_the_tick(self):
        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        book_session(session=session, member=member("queued"), waitlist=True)
        Booking.objects.filter(member__username="seated").update(
            status=Booking.Status.CANCELLED
        )
        promote_next(session)
        moment = timezone.now()
        Booking.objects.filter(member__username="queued").update(hold_expires_at=moment)

        assert sweep_expired_holds(now=moment) == 1
        assert (
            Booking.objects.get(member__username="queued").status
            == Booking.Status.CANCELLED
        )

    def test_unexpired_holds_survive_the_sweep(self):
        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        book_session(session=session, member=member("queued"), waitlist=True)
        Booking.objects.filter(member__username="seated").update(
            status=Booking.Status.CANCELLED
        )
        promoted = promote_next(session)

        assert sweep_expired_holds() == 0
        promoted.refresh_from_db()
        assert promoted.status == Booking.Status.HELD

    def test_sweep_lapses_hold_after_session_start(self):
        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        book_session(session=session, member=member("queued"), waitlist=True)
        Booking.objects.filter(member__username="seated").update(
            status=Booking.Status.CANCELLED
        )
        promote_next(session)
        Booking.objects.filter(member__username="queued").update(
            hold_expires_at=timezone.now() - timedelta(minutes=1)
        )
        ClassSession.objects.filter(pk=session.pk).update(
            starts_at=timezone.now() - timedelta(minutes=1)
        )

        assert sweep_expired_holds() == 1
        assert (
            Booking.objects.get(member__username="queued").status
            == Booking.Status.CANCELLED
        )

    def test_sweep_skips_hold_confirmed_first(self):
        # Schema forbids hold_expires_at on non-HELD rows, so the race
        # shape (HELD at sweep-query time, BOOKED at lock time) is staged
        # by calling _lapse_hold directly on a confirmed booking.
        session, member = _world(capacity=1)
        booking = book_session(session=session, member=member("seated"))

        assert _lapse_hold(booking.pk, timezone.now()) is False
        assert Booking.objects.get(pk=booking.pk).status == Booking.Status.BOOKED
        assert not CancellationRecord.objects.filter(booking=booking).exists()

    def test_sweep_counts_multiple_expired_holds(self):
        session, member = _world(capacity=2)
        book_session(session=session, member=member("seated-a"))
        book_session(session=session, member=member("seated-b"))
        book_session(session=session, member=member("first"), waitlist=True)
        book_session(session=session, member=member("second"), waitlist=True)
        Booking.objects.filter(member__username__in=["seated-a", "seated-b"]).update(
            status=Booking.Status.CANCELLED
        )
        promote_next(session)
        promote_next(session)
        Booking.objects.filter(member__username__in=["first", "second"]).update(
            hold_expires_at=timezone.now() - timedelta(minutes=1)
        )

        assert sweep_expired_holds() == 2
        assert (
            Booking.objects.filter(
                member__username__in=["first", "second"],
                status=Booking.Status.CANCELLED,
            ).count()
            == 2
        )

    def test_sweep_passes_the_seat_to_next_in_line(self):
        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        book_session(session=session, member=member("first"), waitlist=True)
        book_session(session=session, member=member("second"), waitlist=True)
        Booking.objects.filter(member__username="seated").update(
            status=Booking.Status.CANCELLED
        )
        promote_next(session)
        Booking.objects.filter(member__username="first").update(
            hold_expires_at=timezone.now() - timedelta(minutes=1)
        )

        sweep_expired_holds()

        assert (
            Booking.objects.get(member__username="second").status == Booking.Status.HELD
        )


class TestConfirmHold:
    def _held_world(self):
        session, member = _world(capacity=1, credits=10)
        seated = member("seated")
        queued = member("queued")
        book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        Booking.objects.filter(member=seated).update(status=Booking.Status.CANCELLED)
        held = promote_next(session)
        assert held is not None
        return session, queued, waiting

    def test_confirm_charges_and_books(self):
        _session, queued, waiting = self._held_world()
        opening = Membership.objects.get(user=queued).credits_remaining

        confirmed = confirm_booking(booking_id=waiting.pk, actor=queued)

        assert confirmed.status == Booking.Status.BOOKED
        assert confirmed.credits_spent == 1
        assert confirmed.hold_expires_at is None
        assert Membership.objects.get(user=queued).credits_remaining == opening - 1
        assert CreditLedger.objects.filter(
            booking=waiting, reason=CreditLedger.Reason.BOOKING, delta=-1
        ).exists()

    def test_confirm_monthly_books_without_ledger(self):
        session, member = _world(capacity=1)
        seated = member("seated")
        monthly_user = user_with_role(
            session.offering.venue, OrgRole.Role.MEMBER, "monthly", org_wide=True
        )
        with_monthly_plan(monthly_user, session.offering.venue)
        book_session(session=session, member=seated)
        waiting = book_session(session=session, member=monthly_user, waitlist=True)
        Booking.objects.filter(member=seated).update(status=Booking.Status.CANCELLED)
        promote_next(session)

        confirmed = confirm_booking(booking_id=waiting.pk, actor=monthly_user)

        assert confirmed.status == Booking.Status.BOOKED
        assert confirmed.credits_spent == 0
        assert not CreditLedger.objects.filter(booking=waiting).exists()

    def test_confirm_non_held_raises(self):
        session, member = _world(capacity=1)
        booking = book_session(session=session, member=member("seated"))

        with pytest.raises(NotHeld):
            confirm_booking(booking_id=booking.pk, actor=booking.member)

    def test_confirm_cancelled_booking_raises(self):
        session, member = _world(capacity=1)
        booking = book_session(session=session, member=member("seated"))
        cancel_booking(booking_id=booking.pk, actor=booking.member)

        with pytest.raises(AlreadyCancelled):
            confirm_booking(booking_id=booking.pk, actor=booking.member)

    def test_confirm_after_session_start_raises(self):
        session, queued, waiting = self._held_world()
        ClassSession.objects.filter(pk=session.pk).update(
            starts_at=timezone.now() - timedelta(minutes=1)
        )

        with pytest.raises(SessionStarted):
            confirm_booking(booking_id=waiting.pk, actor=queued)

    def test_confirm_expired_hold_raises(self):
        _session, queued, waiting = self._held_world()
        Booking.objects.filter(pk=waiting.pk).update(
            hold_expires_at=timezone.now() - timedelta(minutes=1)
        )

        with pytest.raises(NotHeld):
            confirm_booking(booking_id=waiting.pk, actor=queued)

    def test_confirm_lapsed_pass_raises(self):
        _session, queued, waiting = self._held_world()
        queued.plan_memberships.update(
            starts_on=timezone.now().date() - timedelta(days=60),
            valid_until=timezone.now().date() - timedelta(days=1),
        )

        with pytest.raises(CreditInsufficient):
            confirm_booking(booking_id=waiting.pk, actor=queued)

        waiting.refresh_from_db()
        assert waiting.status == Booking.Status.HELD

    def test_confirm_by_other_member_raises(self):
        _session, _queued, waiting = self._held_world()
        stranger = UserFactory(username="stranger")

        with pytest.raises(PermissionDenied):
            confirm_booking(booking_id=waiting.pk, actor=stranger)


class TestWaitlistNotifications:
    def test_promote_and_expiry_send_mail(self):

        session, member = _world(capacity=1)
        book_session(session=session, member=member("seated"))
        book_session(session=session, member=member("queued"), waitlist=True)
        Booking.objects.filter(member__username="seated").update(
            status=Booking.Status.CANCELLED
        )

        with TestCase.captureOnCommitCallbacks(execute=True):
            promote_next(session)
        assert len(mail.outbox) == 1
        assert "held" in mail.outbox[0].subject.lower()

        Booking.objects.filter(member__username="queued").update(
            hold_expires_at=timezone.now() - timedelta(minutes=1)
        )
        with TestCase.captureOnCommitCallbacks(execute=True):
            sweep_expired_holds()
        assert len(mail.outbox) == 2
        assert "lapsed" in mail.outbox[1].subject.lower()


class TestCancelTriggersPromotion:
    def test_member_cancel_promotes_head(self):
        session, member = _world(capacity=1)
        seated = member("seated")
        queued = member("queued")
        seated_booking = book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)

        cancel_booking(booking_id=seated_booking.pk, actor=seated)

        waiting.refresh_from_db()
        assert waiting.status == Booking.Status.HELD
        assert waiting.credits_spent == 0
        assert waiting.hold_expires_at is not None

    def test_late_cancel_promotes_head(self):
        session, member = _world(capacity=1)
        CancellationPolicyFactory(
            organization=session.offering.venue.organization,
            enforcement=CancellationPolicy.Enforcement.LOSE_CREDIT,
            late_cancel_hours=48,
        )
        seated = member("seated")
        queued = member("queued")
        seated_booking = book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)

        record = cancel_booking(booking_id=seated_booking.pk, actor=seated)

        assert record.cause == "member_cancel"
        waiting.refresh_from_db()
        assert waiting.status == Booking.Status.HELD

    def test_staff_on_behalf_cancel_promotes_head(self):
        session, member = _world(capacity=1)
        seated = member("seated")
        queued = member("queued")
        seated_booking = book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        desk = user_with_role(
            session.offering.venue, OrgRole.Role.FRONTDESK, "wait-desk", org_wide=True
        )

        cancel_booking(
            booking_id=seated_booking.pk,
            actor=desk,
            on_behalf_of=True,
            reason="desk frees the seat",
        )

        waiting.refresh_from_db()
        assert waiting.status == Booking.Status.HELD

    def test_no_show_promotes_head(self):
        session, member = _world(capacity=1)
        seated = member("seated")
        queued = member("queued")
        seated_booking = book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        desk = user_with_role(
            session.offering.venue, OrgRole.Role.FRONTDESK, "wait-door", org_wide=True
        )

        ClassSession.objects.filter(pk=session.pk).update(
            starts_at=timezone.now() - timedelta(minutes=30)
        )

        mark_no_show(booking_id=seated_booking.pk, actor=desk)

        waiting.refresh_from_db()
        assert waiting.status == Booking.Status.HELD

    def test_session_cancel_closes_queue_without_promoting(self):
        session, member = _world(capacity=1)
        seated = member("seated")
        queued = member("queued")
        book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        desk = user_with_role(
            session.offering.venue,
            OrgRole.Role.MANAGER,
            "wait-manager",
            org_wide=True,
        )

        cancel_session(session_id=session.pk, actor=desk, reason="studio closed")

        waiting.refresh_from_db()
        assert waiting.status == Booking.Status.CANCELLED
        assert waiting.credits_spent == 0
        assert (
            Booking.objects.filter(
                session=session, status=Booking.Status.BOOKED
            ).count()
            == 0
        )


class TestWaitlistApi:
    def _client(self, member, venue):

        client = APIClient()
        client.force_authenticate(user=member)
        client.defaults["HTTP_X_VENUE_SLUG"] = venue.slug
        return client

    def test_full_group_waitlist_flag_returns_waitlisted(self):
        session, member = _world(capacity=1)
        venue = session.offering.venue
        seated = member("seated")
        queued = member("queued")
        book_session(session=session, member=seated)
        client = self._client(queued, venue)

        response = client.post(
            "/api/v1/bookings/?waitlist=true", {"session": session.pk}
        )

        assert response.status_code == 201, response.content
        assert response.json()["status"] == "waitlisted"
        assert response.json()["credits_spent"] == 0

    def test_full_group_without_flag_stays_409(self):
        session, member = _world(capacity=1)
        venue = session.offering.venue
        book_session(session=session, member=member("seated"))
        client = self._client(member("turned-away"), venue)

        response = client.post("/api/v1/bookings/", {"session": session.pk})

        assert response.status_code == 409

    def test_private_waitlist_flag_stays_409(self):
        session, member = _world(category=ClassCategory.PRIVATE, capacity=1)
        venue = session.offering.venue
        book_session(session=session, member=member("seated"))
        client = self._client(member("queued"), venue)

        response = client.post(
            "/api/v1/bookings/?waitlist=true", {"session": session.pk}
        )

        assert response.status_code == 409

    def test_confirm_claims_seat_through_the_api(self):
        session, member = _world(capacity=1)
        venue = session.offering.venue
        seated = member("seated")
        queued = member("queued")
        seated_booking = book_session(session=session, member=seated)
        waiting = book_session(session=session, member=queued, waitlist=True)
        Booking.objects.filter(pk=seated_booking.pk).update(
            status=Booking.Status.CANCELLED
        )
        promote_next(session)

        confirm = self._client(queued, venue).post(
            f"/api/v1/bookings/{waiting.pk}/confirm/", {}
        )

        assert confirm.status_code == 200, confirm.content
        assert confirm.json()["status"] == "booked"
        assert confirm.json()["credits_spent"] == 1

    def test_confirm_non_held_is_409(self):
        session, member = _world(capacity=1)
        venue = session.offering.venue
        seated = member("seated")
        booking = book_session(session=session, member=seated)

        confirm = self._client(seated, venue).post(
            f"/api/v1/bookings/{booking.pk}/confirm/", {}
        )

        assert confirm.status_code == 409

    def test_cancel_promotes_through_the_api(self):
        session, member = _world(capacity=1)
        venue = session.offering.venue
        seated = member("seated")
        queued = member("queued")
        seated_booking = book_session(session=session, member=seated)
        self._client(queued, venue).post(
            "/api/v1/bookings/?waitlist=true", {"session": session.pk}
        )

        cancel = self._client(seated, venue).post(
            f"/api/v1/bookings/{seated_booking.pk}/cancel/", {}
        )

        assert cancel.status_code == 200, cancel.content
        queued_booking = Booking.objects.get(session=session, member=queued)
        assert queued_booking.status == Booking.Status.HELD
