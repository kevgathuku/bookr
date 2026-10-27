from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from booking.errors import TeacherUnavailable
from booking.services import book_seat
from organizations.models import Membership, Organization, Venue, VenuePolicy
from scheduling.appointments import (
    Appointment,
    AvailabilityException,
    AvailabilityRule,
    Resource,
)
from scheduling.availability import generate_slots
from scheduling.models import ClassType, Room, ScheduledClass

pytestmark = pytest.mark.django_db

#  Availability seam (pure function, no DB writes in the tests but rows read)
#  - Rules expand to slots; closed/partial exceptions subtract; commitments
#    (appointments + teacher classes) subtract; venue buffer pads both sides.
#  - DST spring-forward: the missing 02:00 wall hour yields no slot.
#
#  Appointment model seam
#  - Same-room / same-teacher overlaps refuse at the DB; cancelled exempt.
#  - Cross-table clash (teacher's class) refused in clean().
#  - book_seat refuses a class whose teacher holds an overlapping
#    appointment (TeacherUnavailable); late_cancel_cutoff is 24h by default.
#
#  Calendar seam: bounded 31d, merges classes + appointments, filters,
#  stays within a query budget on seed-scale data.


def _user(username):
    return get_user_model().objects.create_user(username=username)


_ids = iter(range(100000))


def _unique(prefix, venue):
    return f"{prefix}-{venue.slug}-{next(_ids)}"


def _venue(slug="downtown", tz="UTC"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    return Venue.objects.create(
        organization=org, slug=slug, name=slug.title(), time_zone=tz
    )


def _resource(venue, name="Massage Table", kind="equipment"):
    return Resource.objects.create(venue=venue, name=name, type=kind)


def _rule(resource, weekday=0, start="09:00", end="12:00"):
    def at(value):
        hour, minute = map(int, value.split(":"))
        return time(hour, minute)

    return AvailabilityRule.objects.create(
        resource=resource, weekday=weekday, start_time=at(start), end_time=at(end)
    )


def _appointment(venue, member=None, teacher=None, resource=None, start=None, **over):
    start = start or (timezone.now() + timedelta(days=1))
    defaults = {
        "venue": venue,
        "member": member or _user(_unique("patron", venue)),
        "teacher": teacher or _user(_unique("therapist", venue)),
        "resource": resource,
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
    }
    defaults.update(over)
    return Appointment.objects.create(**defaults)


def _class(venue, teacher, start=None):
    start = start or (timezone.now() + timedelta(days=1))
    class_type, _ = ClassType.objects.get_or_create(
        venue=venue, name="Spin", defaults={"duration_min": 45}
    )
    room, _ = Room.objects.get_or_create(
        venue=venue, name="Studio", defaults={"capacity": 20}
    )
    return ScheduledClass.objects.create(
        venue=venue,
        class_type=class_type,
        room=room,
        teacher=teacher,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


class TestGenerateSlots:
    def test_rule_expands(self):
        venue = _venue()
        resource = _resource(venue)
        _rule(resource, weekday=0)  # Monday 9-12
        monday = date(2026, 10, 26)

        slots = generate_slots(resource, monday, 60)

        assert [(s.hour, s.minute) for s, _ in slots] == [(9, 0), (10, 0), (11, 0)]

    def test_wrong_weekday_empty(self):
        venue = _venue()
        resource = _resource(venue)
        _rule(resource, weekday=0)

        assert generate_slots(resource, date(2026, 10, 27), 60) == []

    def test_closed_exception_empties(self):
        venue = _venue()
        resource = _resource(venue)
        _rule(resource, weekday=0)
        AvailabilityException.objects.create(
            resource=resource, date=date(2026, 10, 26), closed=True
        )

        assert generate_slots(resource, date(2026, 10, 26), 60) == []

    def test_partial_exception_subtracts(self):
        venue = _venue()
        resource = _resource(venue)
        _rule(resource, weekday=0)
        AvailabilityException.objects.create(
            resource=resource,
            date=date(2026, 10, 26),
            start_time=time(10, 0),
            end_time=time(11, 0),
        )

        slots = generate_slots(resource, date(2026, 10, 26), 60)

        assert [(s.hour, s.minute) for s, _ in slots] == [(9, 0), (11, 0)]

    def test_commitments_subtract(self):
        venue = _venue()
        teacher = _user("therapist")
        resource = _resource(venue)
        _rule(resource, weekday=0)
        monday = timezone.datetime(2026, 10, 26, 10, 0, tzinfo=ZoneInfo("UTC"))
        _appointment(venue, teacher=teacher, resource=resource, start=monday)

        slots = generate_slots(resource, date(2026, 10, 26), 60, teacher=teacher)

        assert [(s.hour, s.minute) for s, _ in slots] == [(9, 0), (11, 0)]

    def test_teacher_class_blocks(self):
        venue = _venue()
        teacher = _user("therapist")
        resource = _resource(venue)
        _rule(resource, weekday=0)
        monday = timezone.datetime(2026, 10, 26, 10, 0, tzinfo=ZoneInfo("UTC"))
        _class(venue, teacher, start=monday)

        slots = generate_slots(resource, date(2026, 10, 26), 60, teacher=teacher)

        assert [(s.hour, s.minute) for s, _ in slots] == [(9, 0), (11, 0)]

    def test_buffer_conflicts_back_to_back(self):
        # Venue buffer 10min pads both sides: a slot ending exactly when a
        # commitment starts still conflicts.
        venue = _venue()
        VenuePolicy.objects.create(venue=venue, booking_buffer_minutes=10)
        teacher = _user("therapist")
        resource = _resource(venue)
        _rule(resource, weekday=0)
        monday = timezone.datetime(2026, 10, 26, 10, 0, tzinfo=ZoneInfo("UTC"))
        _appointment(venue, teacher=teacher, resource=resource, start=monday)

        slots = generate_slots(resource, date(2026, 10, 26), 60, teacher=teacher)

        walls = [(s.hour, s.minute) for s, _ in slots]
        assert (9, 0) not in walls  # padded to 9:10, overlaps the 10:00 booking

    def test_dst_gap_has_no_slot(self):
        venue = _venue(slug="nyc", tz="America/New_York")
        resource = _resource(venue)
        _rule(resource, weekday=6, start="00:00", end="05:00")  # Sunday
        sunday = date(2026, 3, 8)  # spring forward: 02:00 never happens

        slots = generate_slots(resource, sunday, 60)
        walls = [s.astimezone(ZoneInfo("America/New_York")) for s, _ in slots]

        assert [(w.hour, w.minute) for w in walls] == [(0, 0), (1, 0), (3, 0), (4, 0)]


class TestAppointmentConstraints:
    def test_overlapping_room_refused(self):
        venue = _venue()
        resource = _resource(venue)
        start = timezone.now() + timedelta(days=1)
        _appointment(venue, resource=resource, start=start)

        with pytest.raises(IntegrityError):
            _appointment(venue, resource=resource, start=start + timedelta(minutes=30))

    def test_overlapping_teacher_refused(self):
        venue = _venue()
        teacher = _user("therapist")
        start = timezone.now() + timedelta(days=1)
        _appointment(venue, teacher=teacher, start=start)

        with pytest.raises(IntegrityError):
            _appointment(
                venue,
                teacher=teacher,
                start=start + timedelta(minutes=30),
            )

    def test_cancelled_exempt(self):
        venue = _venue()
        resource = _resource(venue)
        start = timezone.now() + timedelta(days=1)
        _appointment(
            venue, resource=resource, start=start, status=Appointment.Status.CANCELLED
        )

        kept = _appointment(venue, resource=resource, start=start)

        assert kept.pk is not None

    def test_cross_table_teacher_clash_in_clean(self):
        venue = _venue()
        teacher = _user("therapist")
        start = timezone.now() + timedelta(days=1)
        _class(venue, teacher, start=start)

        clash = Appointment(
            venue=venue,
            member=_user("patron"),
            teacher=teacher,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
        )
        with pytest.raises(ValidationError):
            clash.full_clean()

    def test_late_cancel_cutoff_24h(self):
        venue = _venue()
        VenuePolicy.objects.create(venue=venue)
        start = timezone.now() + timedelta(days=2)
        appointment = _appointment(venue, start=start)

        assert appointment.late_cancel_cutoff() == start - timedelta(hours=24)


class TestAppointmentBookingTarget:
    def test_exactly_one_target(self):
        from booking.models import Booking

        venue = _venue()
        member = _user("member")
        klass = _class(venue, _user("teacher"))

        neither = Booking(venue=venue, member=member, idempotency_key="x1")
        with pytest.raises(ValidationError):
            neither.full_clean()

        appointment = _appointment(venue, member=member)
        both = Booking(
            venue=venue,
            member=member,
            scheduled_class=klass,
            appointment=appointment,
            idempotency_key="x2",
        )
        with pytest.raises(ValidationError):
            both.full_clean()

    def test_teacher_clash_refuses_class_booking(self):
        from passes.models import PassProduct
        from passes.services import issue_pass

        venue = _venue()
        teacher = _user("therapist")
        member = _user("member")
        product = PassProduct.objects.create(
            venue=venue, name="Pack", credits_total=5, validity_days=30
        )
        issue_pass(member, product)
        start = timezone.now() + timedelta(days=1)
        _appointment(venue, member=_user("other"), teacher=teacher, start=start)
        klass = _class(venue, teacher, start=start + timedelta(minutes=30))

        with pytest.raises(TeacherUnavailable):
            book_seat(member, klass, idempotency_key="clash")


class TestCalendar:
    def _world(self):
        venue = _venue()
        member = _user("member")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=member,
            role=Membership.Role.MEMBER,
        )
        teacher = _user("teacher")
        start = timezone.now() + timedelta(days=1)
        _class(venue, teacher, start=start)
        _appointment(
            venue, member=member, teacher=teacher, start=start + timedelta(days=1)
        )
        return venue, member, teacher

    def _client(self, user, slug="downtown"):
        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_VENUE_SLUG"] = slug
        return client

    def test_merges_classes_and_appointments(self):
        _, member, _ = self._world()
        now = timezone.now()

        response = self._client(member).get(
            "/api/v1/calendar/",
            {"from": now.isoformat(), "to": (now + timedelta(days=7)).isoformat()},
        )

        assert response.status_code == 200
        kinds = sorted(event["kind"] for event in response.data)
        assert kinds == ["appointment", "class"]

    def test_window_over_31d_rejected(self):
        _, member, _ = self._world()
        now = timezone.now()

        response = self._client(member).get(
            "/api/v1/calendar/",
            {"from": now.isoformat(), "to": (now + timedelta(days=32)).isoformat()},
        )

        assert response.status_code == 400

    def test_teacher_filter(self):
        _, member, _teacher = self._world()
        now = timezone.now()

        response = self._client(member).get(
            "/api/v1/calendar/",
            {
                "from": now.isoformat(),
                "to": (now + timedelta(days=7)).isoformat(),
                "teacher": _user("stranger").pk,
            },
        )

        assert response.status_code == 200
        assert response.data == []

    def test_query_budget(self):
        _, member, _ = self._world()
        now = timezone.now()
        client = self._client(member)

        with CaptureQueriesContext(connection) as ctx:
            response = client.get(
                "/api/v1/calendar/",
                {"from": now.isoformat(), "to": (now + timedelta(days=7)).isoformat()},
            )

        assert response.status_code == 200
        assert len(ctx) <= 5
