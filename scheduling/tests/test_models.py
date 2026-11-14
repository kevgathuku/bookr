"""Model-layer unit tests: derived ends, queryset edges, overlap rules.

API tests cover these paths indirectly through HTTP; the tests here pin
the exact boundaries (back-to-back, window edges, cancelled slots) that
the schema cannot express and reviews cannot eyeball.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from organizations.models import OrgRole
from scheduling.models import ClassSession, derived_end
from scheduling.sessions import generate_sessions, schedule_session
from tests.factories import (
    ClassOfferingFactory,
    ClassSessionFactory,
    UserFactory,
    VenueFactory,
)

pytestmark = pytest.mark.django_db


def _base():
    return timezone.now().replace(microsecond=0) + timedelta(days=1)


class TestEndsAt:
    def test_derives_from_offering_duration(self):
        offering = ClassOfferingFactory(duration=timedelta(minutes=90))
        session = ClassSessionFactory(offering=offering)

        assert session.ends_at == session.starts_at + timedelta(minutes=90)


class TestSessionQuerySet:
    def test_in_window_excludes_session_ending_at_window_start(self):
        session = ClassSessionFactory(starts_at=_base())

        found = ClassSession.objects.in_window(
            session.ends_at, session.ends_at + timedelta(hours=1)
        )

        assert session.pk not in {row.pk for row in found}

    def test_in_window_excludes_session_starting_at_window_end(self):
        session = ClassSessionFactory(starts_at=_base())

        found = ClassSession.objects.in_window(
            session.starts_at - timedelta(hours=1), session.starts_at
        )

        assert session.pk not in {row.pk for row in found}

    def test_in_window_includes_partial_overlap(self):
        session = ClassSessionFactory(starts_at=_base())

        found = ClassSession.objects.in_window(
            session.starts_at + timedelta(minutes=30),
            session.ends_at + timedelta(hours=1),
        )

        assert {row.pk for row in found} == {session.pk}

    def test_live_excludes_cancelled(self):
        live = ClassSessionFactory()
        ClassSessionFactory(cancelled_at=timezone.now())

        assert {row.pk for row in ClassSession.objects.live()} == {live.pk}

    def test_for_venue_scopes_to_venue(self):
        home = VenueFactory()
        away = VenueFactory()
        wanted = ClassSessionFactory(offering=ClassOfferingFactory(venue=home))
        ClassSessionFactory(offering=ClassOfferingFactory(venue=away))

        assert {row.pk for row in ClassSession.objects.for_venue(home)} == {wanted.pk}

    def test_derived_end_matches_ends_at(self):
        session = ClassSessionFactory()
        row = ClassSession.objects.annotate(computed_end=derived_end()).get(
            pk=session.pk
        )

        # Second precision: sqlite datetime() drops sub-second parts and
        # the domain books whole minutes, so microseconds assert nothing.
        assert row.computed_end.replace(microsecond=0) == session.ends_at.replace(
            microsecond=0
        )


class TestScheduleSession:
    def test_back_to_back_allowed(self):
        offering = ClassOfferingFactory(duration=timedelta(minutes=60))
        first = schedule_session(offering=offering, starts_at=_base())

        second = schedule_session(offering=offering, starts_at=first.ends_at)

        assert second.starts_at == first.ends_at

    def test_partial_overlap_rejected(self):
        offering = ClassOfferingFactory(duration=timedelta(minutes=60))
        first = schedule_session(offering=offering, starts_at=_base())

        with pytest.raises(ValidationError):
            schedule_session(
                offering=offering,
                starts_at=first.starts_at + timedelta(minutes=30),
            )

    def test_cancelled_session_frees_slot(self):
        offering = ClassOfferingFactory(duration=timedelta(minutes=60))
        first = schedule_session(offering=offering, starts_at=_base())
        first.cancelled_at = timezone.now()
        first.save(update_fields=["cancelled_at"])

        retry = schedule_session(offering=offering, starts_at=first.starts_at)

        assert retry.pk != first.pk

    def test_teacher_clash_across_offerings_rejected(self):
        teacher = UserFactory()
        venue = VenueFactory()
        first_offering = ClassOfferingFactory(venue=venue, teacher=teacher)
        second_offering = ClassOfferingFactory(venue=venue, teacher=teacher)
        first = schedule_session(offering=first_offering, starts_at=_base())

        with pytest.raises(ValidationError):
            schedule_session(
                offering=second_offering,
                starts_at=first.starts_at + timedelta(minutes=30),
            )

    def test_naive_datetime_uses_venue_time_zone(self):
        venue = VenueFactory(time_zone="America/New_York")
        offering = ClassOfferingFactory(venue=venue)
        naive = datetime(2026, 5, 4, 9, 30)

        session = schedule_session(offering=offering, starts_at=naive)

        assert session.starts_at == timezone.make_aware(
            naive, ZoneInfo("America/New_York")
        )

    def test_capacity_passthrough(self):
        offering = ClassOfferingFactory()

        session = schedule_session(offering=offering, starts_at=_base(), capacity=7)

        assert session.capacity == 7


class TestGenerateSessions:
    def test_over_limit_rejected(self):
        offering = ClassOfferingFactory(duration=timedelta(minutes=60))
        start = _base()
        rule = start.strftime("DTSTART:%Y%m%dT%H%M%S\nRRULE:FREQ=DAILY;COUNT=300")

        with pytest.raises(ValidationError):
            generate_sessions(
                offering=offering,
                rrule=rule,
                after=start - timedelta(hours=1),
                before=start + timedelta(days=400),
            )

        assert offering.sessions.count() == 0


class TestOfferingTeacherRole:
    def test_pinned_teacher_role_accepted(self):
        offering = ClassOfferingFactory()

        offering.full_clean()

    def test_org_wide_teacher_role_accepted(self):
        offering = ClassOfferingFactory()
        OrgRole.objects.filter(user=offering.teacher).delete()
        OrgRole.objects.create(
            organization=offering.venue.organization,
            venue=None,
            user=offering.teacher,
            role=OrgRole.Role.TEACHER,
        )

        offering.full_clean()

    def test_teacher_without_role_rejected(self):
        offering = ClassOfferingFactory()
        offering.teacher = UserFactory()

        with pytest.raises(ValidationError):
            offering.full_clean()

    def test_other_org_teacher_role_rejected(self):
        offering = ClassOfferingFactory()
        stranger = UserFactory()
        OrgRole.objects.create(
            organization=VenueFactory().organization,
            venue=None,
            user=stranger,
            role=OrgRole.Role.TEACHER,
        )
        offering.teacher = stranger

        with pytest.raises(ValidationError):
            offering.full_clean()

    def test_member_role_is_not_enough(self):
        offering = ClassOfferingFactory()
        member = UserFactory()
        OrgRole.objects.create(
            organization=offering.venue.organization,
            venue=offering.venue,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        offering.teacher = member

        with pytest.raises(ValidationError):
            offering.full_clean()


class TestStr:
    def test_offering_str(self):
        offering = ClassOfferingFactory(title="Spin", category="group")

        assert str(offering) == "Spin (group)"

    def test_session_str(self):
        offering = ClassOfferingFactory(title="Spin")
        starts_at = datetime(2026, 5, 4, 9, 30, tzinfo=ZoneInfo("UTC"))
        session = ClassSessionFactory(offering=offering, starts_at=starts_at)

        assert str(session) == "Spin · 2026-05-04 09:30"
