from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.utils import timezone

from organizations.models import Organization, Venue
from scheduling.models import (
    ClassType,
    Room,
    ScheduledClass,
    TeacherSubstitution,
)
from scheduling.sessions import schedule_session
from tests.factories import (
    ClassOfferingFactory,
    ClassSessionFactory,
    UserFactory,
    VenueFactory,
)

pytestmark = pytest.mark.django_db

#  ClassType / Room
#  - Venue-scoped: same name twice in one venue rejected, same name in two
#    venues accepted (venue autonomy: never shared across venues).
#
#  ScheduledClass
#  - Same room + overlapping time rejected; same teacher + overlapping time
#    rejected (the no-double-booking rule, proven at the ORM seam).
#  - Cancelled rows are exempt: overlapping a cancelled class is allowed.
#  - Back-to-back (one ends exactly when the next starts) is allowed —
#    TSTZRANGE is [) so touching bounds do not overlap.
#  - Different venue with same room-times is allowed (constraint is per-venue).
#  - ends_at must be after starts_at (full_clean, not DB).
#  - Completed rows are immutable: any further save raises.
#  - Capacity = override → room → type default, first non-null wins.
#
#  TeacherSubstitution
#  - Append-only: delete raises; history rows are never removed.


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    return Venue.objects.create(organization=org, slug=slug, name=slug.title())


def _teacher(username="ada"):
    return get_user_model().objects.create_user(username=username)


def _class(venue, room, teacher, start, end, **overrides):
    class_type = overrides.pop(
        "class_type",
        ClassType.objects.get_or_create(
            venue=venue,
            name="Spin",
            defaults={"duration_min": 45, "capacity_default": 20},
        )[0],
    )
    defaults = {
        "venue": venue,
        "class_type": class_type,
        "room": room,
        "teacher": teacher,
        "starts_at": start,
        "ends_at": end,
    }
    defaults.update(overrides)
    return ScheduledClass.objects.create(**defaults)


NOW = timezone.now


def _race_book(offering, start, errors):
    """schedule_session worker for the concurrency test."""
    try:
        schedule_session(offering=offering, starts_at=start)
    except ValidationError as exc:
        errors.append(exc)
    finally:
        # Threads keep their DB connections open otherwise, and teardown
        # can't drop test_bookr while sessions linger.
        connection.close()


class TestClassTypeAndRoom:
    def test_name_unique_per_venue(self):
        venue = _venue()
        ClassType.objects.create(venue=venue, name="Spin", duration_min=45)

        with pytest.raises(IntegrityError):
            ClassType.objects.create(venue=venue, name="Spin", duration_min=30)

    def test_same_name_different_venues(self):
        v1, v2 = _venue("east"), _venue("west")
        ClassType.objects.create(venue=v1, name="Spin", duration_min=45)

        ct = ClassType.objects.create(venue=v2, name="Spin", duration_min=45)

        assert ct.pk is not None

    def test_room_name_unique_per_venue(self):
        venue = _venue()
        Room.objects.create(venue=venue, name="Studio A", capacity=20)

        with pytest.raises(IntegrityError):
            Room.objects.create(venue=venue, name="Studio A", capacity=10)


class TestNoDoubleBooking:
    def _setup(self):
        venue = _venue()
        room = Room.objects.create(venue=venue, name="Studio A", capacity=20)
        teacher = _teacher()
        return venue, room, teacher

    def test_overlapping_room_rejected(self):
        venue, room, teacher = self._setup()
        start = NOW()
        _class(venue, room, teacher, start, start + timedelta(hours=1))

        with pytest.raises(IntegrityError):
            # Same room, overlapping time, different teacher — still refused.
            _class(
                venue,
                room,
                _teacher("grace"),
                start + timedelta(minutes=30),
                start + timedelta(hours=2),
            )

    def test_overlapping_teacher_rejected(self):
        venue, room, teacher = self._setup()
        other_room = Room.objects.create(venue=venue, name="Studio B", capacity=10)
        start = NOW()
        _class(venue, room, teacher, start, start + timedelta(hours=1))

        with pytest.raises(IntegrityError):
            # Same teacher, overlapping time, different room — still refused.
            _class(
                venue,
                other_room,
                teacher,
                start + timedelta(minutes=30),
                start + timedelta(hours=2),
            )

    def test_overlapping_cancelled_allowed(self):
        venue, room, teacher = self._setup()
        start = NOW()
        _class(
            venue,
            room,
            teacher,
            start,
            start + timedelta(hours=1),
            status=ScheduledClass.Status.CANCELLED,
        )

        # Cancelled rows are outside the exclusion predicate → insert succeeds.
        cls = _class(
            venue,
            room,
            teacher,
            start + timedelta(minutes=30),
            start + timedelta(hours=2),
        )

        assert cls.pk is not None

    def test_back_to_back_allowed(self):
        venue, room, teacher = self._setup()
        start = NOW()
        _class(venue, room, teacher, start, start + timedelta(hours=1))

        # Touching bounds do not overlap under TSTZRANGE [) semantics.
        cls = _class(
            venue, room, teacher, start + timedelta(hours=1), start + timedelta(hours=2)
        )

        assert cls.pk is not None

    def test_same_slot_different_venue_allowed(self):
        venue, room, teacher = self._setup()
        other_venue = _venue("uptown")
        other_room = Room.objects.create(
            venue=other_venue, name="Studio A", capacity=20
        )
        start = NOW()
        _class(venue, room, teacher, start, start + timedelta(hours=1))

        cls = _class(
            other_venue, other_room, teacher, start, start + timedelta(hours=1)
        )

        assert cls.pk is not None

    def test_ends_before_starts_rejected(self):
        venue, room, teacher = self._setup()
        start = NOW()
        cls = ScheduledClass(
            venue=venue,
            class_type=ClassType.objects.create(
                venue=venue, name="Spin", duration_min=45
            ),
            room=room,
            teacher=teacher,
            starts_at=start,
            ends_at=start - timedelta(minutes=1),
        )

        with pytest.raises(ValidationError):
            cls.full_clean()


class TestScheduledClassRules:
    def _setup(self):
        venue = _venue()
        room = Room.objects.create(venue=venue, name="Studio A", capacity=20)
        return venue, room, _teacher()

    def test_completed_is_immutable(self):
        venue, room, teacher = self._setup()
        start = NOW()
        cls = _class(
            venue,
            room,
            teacher,
            start,
            start + timedelta(hours=1),
            status=ScheduledClass.Status.COMPLETED,
        )

        cls.capacity_override = 5
        with pytest.raises(ValidationError):
            cls.save()

    def test_capacity_override_first(self):
        venue, room, teacher = self._setup()
        start = NOW()
        cls = _class(
            venue,
            room,
            teacher,
            start,
            start + timedelta(hours=1),
            capacity_override=5,
        )

        assert cls.capacity == 5

    def test_capacity_falls_back_to_room_then_type(self):
        venue = _venue()
        room = Room.objects.create(venue=venue, name="Studio A", capacity=15)
        teacher = _teacher()
        start = NOW()
        cls = _class(venue, room, teacher, start, start + timedelta(hours=1))
        assert cls.capacity == 15  # room capacity

        room.capacity = None
        room.save()
        cls.refresh_from_db()
        assert cls.capacity == 20  # type default (both fixtures use 20)


class TestTeacherSubstitution:
    def test_append_only_delete_raises(self):
        venue = _venue()
        room = Room.objects.create(venue=venue, name="Studio A", capacity=20)
        old_teacher, new_teacher = _teacher("ada"), _teacher("grace")
        admin = _teacher("root")
        start = NOW()
        cls = _class(venue, room, old_teacher, start, start + timedelta(hours=1))
        sub = TeacherSubstitution.objects.create(
            scheduled_class=cls,
            old_teacher=old_teacher,
            new_teacher=new_teacher,
            reason="sick",
            created_by=admin,
        )

        with pytest.raises(ValidationError):
            sub.delete()

        # History kept: the row is still there.
        assert TeacherSubstitution.objects.filter(pk=sub.pk).exists()


class TestSessionOverlap:
    """Same-teacher sessions may not overlap; cancelled ones free the slot.

    Ends derive from start plus offering duration, so overlap is checked
    against the derived window, not a stored column.
    """

    def _offering(self, **kwargs):
        kwargs.setdefault("venue", VenueFactory())
        kwargs.setdefault("teacher", UserFactory())
        return ClassOfferingFactory(**kwargs)

    def test_overlapping_same_offering_rejected(self):

        session = ClassSessionFactory(offering=self._offering())

        with pytest.raises(ValidationError):
            schedule_session(
                offering=session.offering,
                starts_at=session.starts_at + timedelta(minutes=30),
            )

    def test_cancelled_session_frees_slot(self):

        session = ClassSessionFactory(offering=self._offering())
        session.cancelled_at = timezone.now()
        session.save(update_fields=["cancelled_at"])

        made = schedule_session(offering=session.offering, starts_at=session.starts_at)

        assert made.pk is not None

    def test_teacher_cannot_double_book_across_offerings(self):

        first = ClassSessionFactory(offering=self._offering())
        other = ClassOfferingFactory(
            venue=first.offering.venue, teacher=first.offering.teacher
        )

        with pytest.raises(ValidationError):
            schedule_session(
                offering=other, starts_at=first.starts_at + timedelta(minutes=30)
            )

    def test_back_to_back_allowed(self):

        first = ClassSessionFactory(offering=self._offering())
        made = schedule_session(offering=first.offering, starts_at=first.ends_at)
        assert made.pk is not None

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_same_slot_single_winner(self):
        # Plain django_db wraps the test in a transaction other threads
        # can't see into — so this one commits for real (flushed after).

        offering = ClassOfferingFactory()
        start = timezone.now() + timedelta(days=1)
        errors = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: _race_book(offering, start, errors), range(2)))
        assert len(errors) == 1  # loser hits the overlap check
        assert offering.sessions.count() == 1
