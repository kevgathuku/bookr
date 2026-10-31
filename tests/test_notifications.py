"""Post-commit member notices for cancels (bookr-0sr.6).

Cancellation writes stay silent; the email goes out only after the
transaction commits, so members are never notified of rolled-back state.
Tests assert via mail.outbox inside captureOnCommitCallbacks (plain
TestCase never commits, so callbacks would otherwise never fire).
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from booking.cancellations import cancel_booking, cancel_session
from booking.models import CancellationPolicy
from booking.services import book_session
from scheduling.catalogue import ClassCategory
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

LATE = CancellationPolicy.Enforcement.LOSE_CREDIT


def _venue(slug):
    return VenueFactory(slug=slug)


def _session(venue, starts_in_hours=48):
    offering = ClassOfferingFactory(venue=venue, category=ClassCategory.GROUP)
    return ClassSessionFactory(
        offering=offering,
        starts_at=timezone.now() + timedelta(hours=starts_in_hours),
    )


def _member(username, venue, credits=10):
    from organizations.models import OrgRole

    user = UserFactory(username=username)
    OrgRoleFactory(
        organization=venue.organization,
        venue=None,
        user=user,
        role=OrgRole.Role.MEMBER,
    )
    plan = MembershipPlanFactory(organization=venue.organization)
    PlanMembershipFactory(user=user, plan=plan, credits_remaining=credits)
    return user


def _staff(username, venue):
    from organizations.models import OrgRole

    user = UserFactory(username=username)
    OrgRoleFactory(
        organization=venue.organization,
        venue=None,
        user=user,
        role=OrgRole.Role.FRONTDESK,
    )
    return user


def _policy(org, enforcement, late_cancel_hours=12):
    return CancellationPolicy.objects.create(
        organization=org,
        enforcement=enforcement,
        late_cancel_hours=late_cancel_hours,
    )


def _book(member, session, price=2):
    session.offering.credit_cost = price
    session.offering.save(update_fields=["credit_cost"])
    return book_session(session=session, member=member)


def _cancel(member, booking, **kwargs):
    kwargs.setdefault("reason", "change of plans")
    with TestCase.captureOnCommitCallbacks(execute=True) as callbacks:
        record = cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            **kwargs,
        )
    assert callbacks
    return record


class TestMemberCancelNotice:
    def test_early_cancel_says_refunded(self):
        venue = _venue("notice-early")
        session = _session(venue)
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, LATE)
        booking = _book(member, session)

        _cancel(member, booking)

        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert "cancelled" in mail.outbox[0].subject.lower()
        assert "refunded" in body
        assert member.email or member.username in mail.outbox[0].to[0]

    def test_late_forfeit_says_forfeited(self):
        venue = _venue("notice-forfeit")
        session = _session(venue, starts_in_hours=2)
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, LATE)
        booking = _book(member, session)

        _cancel(member, booking)

        assert len(mail.outbox) == 1
        assert "forfeit" in mail.outbox[0].body

    def test_no_notice_until_commit(self):
        # Inside the TestCase's outer transaction the commit never happens,
        # so a correctly deferred notice stays silent. This fails if the
        # service ever calls the notifier inline instead of on_commit.
        venue = _venue("notice-deferred")
        session = _session(venue)
        member = _member("m1", venue, credits=10)
        _policy(venue.organization, LATE)
        booking = _book(member, session)

        cancel_booking(
            booking_id=booking.pk,
            actor=member,
            now=timezone.now(),
            reason="change of plans",
        )

        assert len(mail.outbox) == 0


class TestSessionCancelNotice:
    def test_each_member_gets_refund_notice(self):
        venue = _venue("notice-session")
        session = _session(venue, starts_in_hours=2)
        members = [_member(f"m{i}", venue, credits=10) for i in range(2)]
        for member in members:
            _book(member, session)
        desk = _staff("desk", venue)

        with TestCase.captureOnCommitCallbacks(execute=True):
            records = cancel_session(
                session_id=session.pk, actor=desk, reason="teacher sick"
            )

        assert len(records) == 2
        assert len(mail.outbox) == 2
        assert all("cancelled" in message.subject.lower() for message in mail.outbox)
        assert all("refund" in message.body for message in mail.outbox)
