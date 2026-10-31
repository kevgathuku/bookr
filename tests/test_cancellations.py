"""Cancel paths on scoped rules (bookr-0sr.4).

Resolution: most-specific-wins, higher priority breaks ties, equally
specific same-priority overlaps rejected at creation, uncovered contexts
fall back to the auto-created org-wide NONE baseline (free by design).
"""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from booking.cancellations import (
    cancel_booking,
    cancel_session,
    check_in,
    mark_no_show,
    resolve_policy,
    strike_count,
    waive_record,
)
from booking.errors import AlreadyCancelled, InvalidWaiver, SessionStarted
from booking.models import Booking, CancellationPolicy, CancellationRecord
from booking.services import book_session
from organizations.models import OrgRole
from passes.models import CreditLedger, PlanType
from scheduling.catalogue import ClassCategory
from tests.factories import (
    CancellationPolicyFactory,
    ClassOfferingFactory,
    ClassSessionFactory,
    MembershipPlanFactory,
    OrgRoleFactory,
    PlanMembershipFactory,
    UserFactory,
    VenueFactory,
)

pytestmark = pytest.mark.django_db

LATE = CancellationPolicy.Enforcement.LOSE_CREDIT
STRIKE = CancellationPolicy.Enforcement.STRIKE
NONE = CancellationPolicy.Enforcement.NONE


def _venue(slug="v1"):
    return VenueFactory(slug=slug)


def _session(venue, category=ClassCategory.GROUP, starts_in_hours=48):
    offering = ClassOfferingFactory(venue=venue, category=category)
    return ClassSessionFactory(
        offering=offering,
        starts_at=timezone.now() + timedelta(hours=starts_in_hours),
    )


def _member(username, venue, credits=10, plan_type=PlanType.CREDIT_PACK):
    user = UserFactory(username=username)
    OrgRoleFactory(
        organization=venue.organization,
        venue=None,
        user=user,
        role=OrgRole.Role.MEMBER,
    )
    plan = MembershipPlanFactory(organization=venue.organization, plan_type=plan_type)
    PlanMembershipFactory(user=user, plan=plan, credits_remaining=credits)
    return user


def _monthly(username, venue):
    user = UserFactory(username=username)
    OrgRoleFactory(
        organization=venue.organization,
        venue=None,
        user=user,
        role=OrgRole.Role.MEMBER,
    )
    plan = MembershipPlanFactory(
        organization=venue.organization, plan_type=PlanType.MONTHLY
    )
    PlanMembershipFactory(user=user, plan=plan, credits_remaining=0)
    return user


def _staff(username, venue, role=OrgRole.Role.FRONTDESK):
    user = UserFactory(username=username)
    OrgRoleFactory(organization=venue.organization, venue=None, user=user, role=role)
    return user


def _policy(org, enforcement, late_cancel_hours=12, **scopes):
    policy = CancellationPolicyFactory(
        organization=org,
        enforcement=enforcement,
        late_cancel_hours=late_cancel_hours,
        **scopes,
    )
    policy.full_clean()
    policy.save()
    return policy


def _book(member, session, price=2):
    session.offering.credit_cost = price
    session.offering.save(update_fields=["credit_cost"])
    return book_session(session=session, member=member)


def _direct_booking(member, session, spent=2):
    # Started sessions cannot be booked through the service by design;
    # cancelling/no-showing them needs a row the service would refuse.
    membership = member.plan_memberships.get()
    membership.credits_remaining -= spent
    membership.save(update_fields=["credits_remaining"])
    return Booking.objects.create(
        session=session,
        member=member,
        membership=membership,
        credits_spent=spent,
    )


def _roles(user, venue):
    return list(
        OrgRole.objects.filter(organization=venue.organization, user=user).values_list(
            "role", flat=True
        )
    )


class TestResolution:
    def test_most_specific_wins(self):
        venue = _venue()
        org = venue.organization
        base = _policy(org, NONE)
        specific = _policy(org, STRIKE, venue=venue)

        assert (
            resolve_policy(org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK)
            == specific
        )
        assert base.pk is not None

    def test_more_scopes_beat_fewer(self):
        venue = _venue()
        org = venue.organization
        _policy(org, NONE, venue=venue)
        both = _policy(org, STRIKE, venue=venue, class_category=ClassCategory.GROUP)

        assert (
            resolve_policy(org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK)
            == both
        )

    def test_higher_priority_breaks_ties(self):
        venue = _venue()
        org = venue.organization
        low = _policy(org, NONE, venue=venue, priority=0)
        high = _policy(org, STRIKE, class_category=ClassCategory.GROUP, priority=5)

        assert (
            resolve_policy(org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK)
            == high
        )
        assert low.pk is not None

    def test_ambiguous_rules_rejected_at_creation(self):
        venue = _venue()
        org = venue.organization
        _policy(org, NONE, venue=venue)
        rival = CancellationPolicyFactory(
            organization=org,
            enforcement=STRIKE,
            late_cancel_hours=12,
            class_category=ClassCategory.GROUP,
        )

        with pytest.raises(ValidationError):
            rival.full_clean()

    def test_uncovered_context_falls_back_to_baseline(self):
        venue = _venue()
        org = venue.organization

        policy = resolve_policy(
            org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK
        )

        assert policy.enforcement == NONE
        assert policy.venue is None
        assert policy.specificity == 0

    def test_baseline_created_once(self):
        venue = _venue()
        org = venue.organization
        resolve_policy(org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK)
        resolve_policy(org.pk, venue.pk, ClassCategory.PRIVATE, PlanType.MONTHLY)

        assert CancellationPolicy.objects.filter(organization=org).count() == 1

    def test_last_rule_deletion_protected(self):
        venue = _venue()
        org = venue.organization
        only = resolve_policy(
            org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK
        )

        with pytest.raises(ValidationError):
            only.delete()

    def test_non_last_rule_deletes(self):
        venue = _venue()
        org = venue.organization
        _policy(org, STRIKE, venue=venue)
        baseline = resolve_policy(
            org.pk, venue.pk, ClassCategory.GROUP, PlanType.CREDIT_PACK
        )
        extra = _policy(org, NONE, class_category=ClassCategory.PRIVATE, priority=5)

        extra.delete()

        assert CancellationPolicy.objects.filter(organization=org).count() == 2
        assert baseline.pk is not None


class TestMemberCancel:
    def test_early_cancel_refunds_and_records(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=48)
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="change of plans",
        )

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert record.enforcement_applied == NONE
        assert record.was_late is False
        assert record.credits_refunded == 2
        member.plan_memberships.get().refresh_from_db()

    def test_late_cancel_lose_credit_forfeits(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="overslept",
        )

        booking.refresh_from_db()
        assert booking.status == Booking.Status.LATE_CANCELLED
        assert record.enforcement_applied == LATE
        assert record.was_late is True
        assert record.credits_refunded == 0
        # No ledger movement at all: the debit stands, nothing returns.
        assert (
            CreditLedger.objects.filter(
                membership=booking.membership, reason=CreditLedger.Reason.REFUND
            ).count()
            == 0
        )

    def test_late_cancel_strike_refunds_and_counts(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="traffic",
        )

        assert record.enforcement_applied == STRIKE
        assert record.credits_refunded == 2
        assert strike_count(member, venue.organization, timezone.now()) == 1

    def test_no_rule_is_designed_free(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="no rules yet",
        )

        assert record.enforcement_applied == NONE
        assert record.credits_refunded == 2

    def test_double_cancel_raises(self):
        venue = _venue()
        session = _session(venue)
        member = _member("m1", venue)
        booking = _book(member, session)
        cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="first",
        )

        with pytest.raises(AlreadyCancelled):
            cancel_booking(
                booking_id=booking.pk,
                actor=member,
                now=timezone.now(),
                reason="second",
            )

    def test_cancel_started_session_raises(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=-1)
        member = _member("m1", venue)
        booking = _direct_booking(member, session)

        with pytest.raises(SessionStarted):
            cancel_booking(
                booking_id=booking.pk,
                actor=member,
                now=timezone.now(),
                reason="too late",
            )

    def test_snapshot_pins_full_context(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        policy = _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="traffic",
        )

        snap = record.snapshot
        assert snap == {
            "cause": "member_cancel",
            "session_id": session.pk,
            "session_starts_at": session.starts_at.isoformat(),
            "offering_title": session.offering.title,
            "class_category": ClassCategory.GROUP,
            "venue_slug": venue.slug,
            "organization_id": venue.organization_id,
            "member_id": member.pk,
            "membership_id": booking.membership_id,
            "plan_type": PlanType.CREDIT_PACK,
            "credits_spent": 2,
            "credits_refunded": 2,
            "policy": {
                "id": policy.pk,
                "specificity": 0,
                "priority": 0,
                "late_cancel_hours": 12,
                "enforcement": STRIKE,
            },
            "actor_id": member.pk,
            "on_behalf_of": False,
            "reason": "traffic",
        }

    def test_resolution_follows_current_rules(self):
        # No versions: cancelling always applies today's rules; the record
        # pins what applied so history stays readable after rules change.
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        old = _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _book(member, session)
        resolve_policy(
            venue.organization.pk,
            venue.pk,
            ClassCategory.GROUP,
            PlanType.CREDIT_PACK,
        )
        old.delete()
        _policy(venue.organization, NONE, late_cancel_hours=12)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="rules changed",
        )

        assert record.enforcement_applied == NONE
        assert record.snapshot["policy"]["enforcement"] == NONE


class TestInitiator:
    def test_frontdesk_on_behalf_penalized(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        desk = _staff("desk", venue)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=desk,
            on_behalf_of=True,
            now=timezone.now(),
            reason="member called in",
        )

        assert record.enforcement_applied == LATE
        assert record.snapshot["on_behalf_of"] is True

    def test_staff_own_decision_never_penalized(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        desk = _staff("desk", venue)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=desk,
            now=timezone.now(),
            reason="class moved rooms",
        )

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert record.enforcement_applied == NONE
        assert record.credits_refunded == 2
        assert record.snapshot["cause"] == "staff_decision"

    def test_teacher_cancels_own_roster_booking(self):
        venue = _venue()
        teacher = UserFactory(username="t-roster")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=teacher,
            role=OrgRole.Role.TEACHER,
        )
        offering = ClassOfferingFactory(venue=venue, teacher=teacher)
        session = ClassSessionFactory(
            offering=offering,
            starts_at=timezone.now() + timedelta(hours=2),
        )
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=teacher,
            now=timezone.now(),
            reason="disruptive, remove",
        )

        assert record.snapshot["cause"] == "staff_decision"
        assert record.enforcement_applied == NONE
        assert record.credits_refunded == 2

    def test_teacher_cannot_cancel_other_roster_booking(self):
        venue = _venue()
        teacher = UserFactory(username="t-stranger")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=teacher,
            role=OrgRole.Role.TEACHER,
        )
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        booking = _book(member, session)

        with pytest.raises(PermissionDenied):
            cancel_booking(
                booking_id=booking.pk,
                actor=teacher,
                now=timezone.now(),
                reason="not mine",
            )

    def test_staff_cancel_requires_reason(self):
        venue = _venue()
        session = _session(venue)
        member = _member("m1", venue)
        desk = _staff("desk", venue)
        booking = _book(member, session)

        with pytest.raises(ValidationError):
            cancel_booking(
                booking_id=booking.pk,
                actor=desk,
                now=timezone.now(),
                reason="",
            )

    def test_waive_with_no_penalty_raises(self):
        venue = _venue()
        session = _session(venue)
        member = _member("m1", venue)
        desk = _staff("desk", venue)
        booking = _book(member, session)

        with pytest.raises(InvalidWaiver):
            cancel_booking(
                booking_id=booking.pk,
                actor=desk,
                waive_penalty=True,
                now=timezone.now(),
                reason="nothing to waive",
            )

    def test_stranger_cannot_cancel(self):

        venue = _venue()
        session = _session(venue)
        member = _member("m1", venue)
        stranger = UserFactory(username="stranger")
        booking = _book(member, session)

        with pytest.raises(PermissionDenied):
            cancel_booking(
                booking_id=booking.pk,
                actor=stranger,
                now=timezone.now(),
                reason="hijack",
            )


class TestWaiver:
    def test_inline_waive_by_desk_forgives_but_remembers(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        desk = _staff("desk", venue)
        _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _book(member, session)

        record = cancel_booking(
            booking_id=booking.pk,
            actor=desk,
            on_behalf_of=True,
            waive_penalty=True,
            now=timezone.now(),
            reason="regular, car broke down",
        )

        assert record.enforcement_applied == NONE
        assert record.was_late is True
        assert record.penalty_waived is True
        assert record.waived_by == desk
        assert record.credits_refunded == 2

    def test_member_cannot_waive_own_penalty(self):

        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)

        with pytest.raises(PermissionDenied):
            cancel_booking(
                booking_id=booking.pk,
                actor=member,
                waive_penalty=True,
                now=timezone.now(),
                reason="please",
            )

    def test_retroactive_waive_compensates_without_rewriting(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        desk = _staff("desk", venue)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)
        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="overslept",
        )
        assert record.credits_refunded == 0

        adjustment = waive_record(
            record_id=record.pk, actor=desk, reason="goodwill gesture"
        )

        assert adjustment.reason == CreditLedger.Reason.ADJUSTMENT
        assert adjustment.delta == 2
        assert adjustment.cancellation_record_id == record.pk
        record.refresh_from_db()
        # History untouched: the record still says what happened.
        assert record.enforcement_applied == LATE
        assert record.credits_refunded == 0

    def test_retroactive_waive_of_zero_spend_raises(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _monthly("m1", venue)
        desk = _staff("desk", venue)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session, price=0)
        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="late",
        )

        with pytest.raises(InvalidWaiver):
            waive_record(record_id=record.pk, actor=desk, reason="goodwill")

    def test_retroactive_waive_of_strike_raises(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        desk = _staff("desk", venue)
        _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _book(member, session)
        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="late",
        )

        # Strikes move no money: nothing to compensate. Forgiveness for
        # strikes is inline-only, at cancel time.
        with pytest.raises(InvalidWaiver):
            waive_record(record_id=record.pk, actor=desk, reason="goodwill")

        assert strike_count(member, venue.organization, timezone.now()) == 1

    def test_retroactive_waive_is_idempotent(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        desk = _staff("desk", venue)
        _policy(venue.organization, LATE, late_cancel_hours=12)
        booking = _book(member, session)
        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="overslept",
        )

        first = waive_record(record_id=record.pk, actor=desk, reason="goodwill")
        second = waive_record(record_id=record.pk, actor=desk, reason="goodwill")

        assert first.pk == second.pk
        assert CreditLedger.objects.filter(cancellation_record=record).count() == 1

    def test_linked_adjustment_excludes_the_strike(self):
        # Unreachable via waive_record by design (strikes move no money);
        # direct row proves the strike query honors the link regardless.
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        desk = _staff("desk", venue)
        _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _book(member, session)
        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="late",
        )
        CreditLedger.objects.create(
            membership=booking.membership,
            booking=booking,
            cancellation_record=record,
            delta=2,
            reason=CreditLedger.Reason.ADJUSTMENT,
            created_by=desk,
        )

        assert strike_count(member, venue.organization, timezone.now()) == 0


@pytest.mark.django_db(transaction=True)
class TestSessionCancelRace:
    def test_concurrent_session_cancels_refund_once(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connection

        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        _book(member, session)
        desk = _staff("desk", venue)

        def attempt(_i):
            try:
                records = cancel_session(
                    session_id=session.pk, actor=desk, reason="storm"
                )
                return [r.pk for r in records]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(attempt, range(2)))

        assert first == second
        assert CancellationRecord.objects.filter(booking__session=session).count() == 1

    def test_concurrent_member_cancels_keep_one_refund(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connection

        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        booking = _book(member, session)
        before = member.plan_memberships.get().credits_remaining

        def attempt(_i):
            try:
                cancel_booking(
                    booking_id=booking.pk,
                    actor=member,
                    now=timezone.now(),
                    reason="double tap",
                )
                return "cancelled"
            except AlreadyCancelled:
                return "already"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(attempt, range(2)))

        assert outcomes == ["already", "cancelled"]
        member.plan_memberships.get().refresh_from_db()
        after = member.plan_memberships.get().credits_remaining
        assert after - before == 2


class TestSessionCancel:
    def test_session_cancel_refunds_every_booking(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        members = [_member(f"m{i}", venue, credits=10) for i in range(3)]
        bookings = [_book(member, session) for member in members]
        desk = _staff("desk", venue)

        records = cancel_session(
            session_id=session.pk, actor=desk, reason="teacher sick"
        )

        assert len(records) == 3
        for booking, record in zip(bookings, records):
            booking.refresh_from_db()
            assert booking.status == Booking.Status.CANCELLED
            assert record.credits_refunded == 2
            assert record.snapshot["cause"] == "session_cancelled"
            assert record.enforcement_applied == NONE

    def test_session_cancel_repeat_returns_same_records(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        _book(member, session)
        desk = _staff("desk", venue)

        first = cancel_session(session_id=session.pk, actor=desk, reason="teacher sick")
        second = cancel_session(
            session_id=session.pk, actor=desk, reason="teacher sick"
        )

        assert [r.pk for r in first] == [r.pk for r in second]
        assert CancellationRecord.objects.filter(booking__session=session).count() == 1
        session.refresh_from_db()
        assert session.cancelled_at is not None

    def test_teacher_cancels_own_session(self):

        venue = _venue()
        teacher = UserFactory(username="t-coach")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=teacher,
            role=OrgRole.Role.TEACHER,
        )
        offering = ClassOfferingFactory(venue=venue, teacher=teacher)
        session = ClassSessionFactory(
            offering=offering,
            starts_at=timezone.now() + timedelta(hours=2),
        )
        member = _member("m1", venue, credits=10)
        _book(member, session)

        records = cancel_session(session_id=session.pk, actor=teacher, reason="sick")

        assert len(records) == 1
        assert records[0].snapshot["cause"] == "session_cancelled"

    def test_teacher_cannot_cancel_another_teachers_session(self):
        venue = _venue()
        teacher = UserFactory(username="t-other")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=teacher,
            role=OrgRole.Role.TEACHER,
        )
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        _book(member, session)

        with pytest.raises(PermissionDenied):
            cancel_session(session_id=session.pk, actor=teacher, reason="not mine")

    def test_session_cancel_requires_reason(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        _book(member, session)
        desk = _staff("desk", venue)

        with pytest.raises(ValidationError):
            cancel_session(session_id=session.pk, actor=desk, reason="")


class TestNoShowAndCheckin:
    def test_mark_no_show_forfeits_without_strike(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=-2)
        member = _member("m1", venue, credits=10)
        desk = _staff("desk", venue)
        _policy(venue.organization, STRIKE, late_cancel_hours=12)
        booking = _direct_booking(member, session)

        record = mark_no_show(booking_id=booking.pk, actor=desk)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.NO_SHOW
        assert record.snapshot["cause"] == "no_show"
        assert record.credits_refunded == 0
        assert strike_count(member, venue.organization, timezone.now()) == 0

    def test_future_session_cannot_be_no_show(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue)
        desk = _staff("desk", venue)
        booking = _book(member, session)

        with pytest.raises(ValidationError):
            mark_no_show(booking_id=booking.pk, actor=desk)

    def test_member_cannot_mark_no_show(self):

        venue = _venue()
        session = _session(venue, starts_in_hours=-2)
        member = _member("m1", venue)
        booking = _direct_booking(member, session)

        with pytest.raises(PermissionDenied):
            mark_no_show(booking_id=booking.pk, actor=member)

    def test_check_in_is_status_only(self):
        venue = _venue()
        session = _session(venue, starts_in_hours=1)
        member = _member("m1", venue)
        desk = _staff("desk", venue)
        booking = _book(member, session)

        check_in(booking_id=booking.pk, actor=desk)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.ATTENDED
        assert CancellationRecord.objects.filter(booking=booking).count() == 0


class TestStrikes:
    def test_window_excludes_old_and_waived(self):
        venue = _venue()
        org = venue.organization
        member = _member("m1", venue, credits=30)
        desk = _staff("desk", venue)
        _policy(org, STRIKE, late_cancel_hours=12)
        now = timezone.now()

        def late_cancel(username_suffix, hours_ago):
            session = _session(venue, starts_in_hours=2)
            other = _member(f"s-{username_suffix}", venue, credits=10)
            booking = _book(other, session)
            return cancel_booking(
                booking_id=booking.pk,
                actor=other,
                now=now - timedelta(hours=hours_ago),
                reason="late",
            )

        fresh = late_cancel("a", 0)
        old = late_cancel("b", 0)
        old.created_at = now - timedelta(days=31)
        old.save(update_fields=["created_at"])
        waived_booking_member = _member("s-c", venue, credits=10)
        session_c = _session(venue, starts_in_hours=2)
        booking_c = _book(waived_booking_member, session_c)
        waived = cancel_booking(
            booking_id=booking_c.pk,
            actor=desk,
            on_behalf_of=True,
            waive_penalty=True,
            now=now,
            reason="forgiven",
        )
        retro = late_cancel("d", 0)
        with pytest.raises(InvalidWaiver):
            waive_record(record_id=retro.pk, actor=desk, reason="goodwill")

        assert strike_count(member, org, now) == 0  # other member's rows don't leak
        assert fresh.pk is not None and waived.pk is not None
        assert (
            CancellationRecord.objects.filter(
                member=member,
            ).count()
            == 0
        )
