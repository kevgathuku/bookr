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
from common.ids import BookingId, SessionId
from organizations.models import OrgRole
from tests.factories import (
    book,
    make_member,
    make_policy,
    make_session,
    make_venue,
    user_with_role,
)

pytestmark = pytest.mark.django_db

LATE = CancellationPolicy.Enforcement.LOSE_CREDIT


def _cancel(member, booking, **kwargs):
    kwargs.setdefault("reason", "change of plans")
    with TestCase.captureOnCommitCallbacks(execute=True) as callbacks:
        record = cancel_booking(
            booking_id=BookingId(booking.pk),
            actor=member,
            now=timezone.now(),
            **kwargs,
        )
    assert callbacks
    return record


class TestMemberCancelNotice:
    def test_early_cancel_says_refunded(self):
        venue = make_venue("notice-early")
        session = make_session(venue)
        member = make_member("m1", venue, credits=10)
        make_policy(venue.organization, LATE)
        booking = book(member, session)

        _cancel(member, booking)

        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert "cancelled" in mail.outbox[0].subject.lower()
        assert "refunded" in body
        assert mail.outbox[0].to == [member.email]

    def test_missing_email_raises_instead_of_fabricating(self):
        venue = make_venue("notice-noemail")
        session = make_session(venue)
        member = make_member("m1", venue, credits=10)
        member.email = ""
        member.save(update_fields=["email"])
        make_policy(venue.organization, LATE)
        booking = book(member, session)

        with (
            pytest.raises(
                ValueError,
                match="email",
            ),
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            cancel_booking(
                booking_id=BookingId(booking.pk),
                actor=member,
                now=timezone.now(),
                reason="change of plans",
            )

        assert len(mail.outbox) == 0

    def test_late_forfeit_says_forfeited(self):
        venue = make_venue("notice-forfeit")
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=2))
        member = make_member("m1", venue, credits=10)
        make_policy(venue.organization, LATE)
        booking = book(member, session)

        _cancel(member, booking)

        assert len(mail.outbox) == 1
        assert "forfeit" in mail.outbox[0].body

    def test_no_notice_until_commit(self):
        # Inside the TestCase's outer transaction the commit never happens,
        # so a correctly deferred notice stays silent. This fails if the
        # service ever calls the notifier inline instead of on_commit.
        venue = make_venue("notice-deferred")
        session = make_session(venue)
        member = make_member("m1", venue, credits=10)
        make_policy(venue.organization, LATE)
        booking = book(member, session)

        cancel_booking(
            booking_id=BookingId(booking.pk),
            actor=member,
            now=timezone.now(),
            reason="change of plans",
        )

        assert len(mail.outbox) == 0


class TestSessionCancelNotice:
    def test_each_member_gets_refund_notice(self):
        venue = make_venue("notice-session")
        session = make_session(venue, starts_at=timezone.now() + timedelta(hours=2))
        members = [make_member(f"m{i}", venue, credits=10) for i in range(2)]
        for member in members:
            book(member, session)
        desk = user_with_role(venue, OrgRole.Role.FRONTDESK, "desk", org_wide=True)

        with TestCase.captureOnCommitCallbacks(execute=True):
            records = cancel_session(
                session_id=SessionId(session.pk), actor=desk, reason="teacher sick"
            )

        assert len(records) == 2
        assert len(mail.outbox) == 2
        assert all("cancelled" in message.subject.lower() for message in mail.outbox)
        assert all("refund" in message.body for message in mail.outbox)
