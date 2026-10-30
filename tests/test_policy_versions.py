from datetime import timedelta

import pytest
from django.utils import timezone

from booking.cancellations import cancel_booking
from booking.models import Booking
from organizations.models import VenuePolicy
from scheduling.models import ClassType, Room, ScheduledClass
from tests.factories import MembershipFactory, UserFactory, VenueFactory

pytestmark = pytest.mark.django_db

#  Policy versions: overlapping windows allowed, members pinned to an
#  explicit version keep it (grandfathered); everyone else follows current.


def _class(venue, days=2):
    start = timezone.now() + timedelta(days=days)
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
        teacher=UserFactory(),
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


def _book(member, venue, klass, key):
    return Booking.objects.create(
        member=member,
        venue=venue,
        scheduled_class=klass,
        status=Booking.Status.CONFIRMED,
        idempotency_key=key,
    )


class TestVersions:
    def test_activate_assigns_versions_and_allows_overlap(self):
        venue = VenueFactory()
        first = VenuePolicy.objects.activate(venue, class_late_cancel_hours=8)
        second = VenuePolicy.objects.activate(venue, class_late_cancel_hours=4)

        assert (first.version, second.version) == (1, 2)
        overlapping = VenuePolicy.objects.create(
            venue=venue, valid_until=None, class_late_cancel_hours=12
        )
        assert overlapping.version == 3
        assert venue.current_policy.pk == overlapping.pk

    def test_current_policy_is_latest_open(self):
        venue = VenueFactory()
        VenuePolicy.objects.activate(venue, class_late_cancel_hours=8)
        latest = VenuePolicy.objects.activate(venue, class_late_cancel_hours=4)

        assert venue.current_policy.pk == latest.pk


class TestGrandfathering:
    def test_pinned_member_keeps_old_window(self):
        venue = VenueFactory()
        # Same +2d class discriminates: pinned 8h window -> on time,
        # current 72h window -> late. A shared code path cannot pass both.
        old = VenuePolicy.objects.activate(venue, class_late_cancel_hours=8)
        VenuePolicy.objects.activate(venue, class_late_cancel_hours=72)
        member = MembershipFactory(
            organization=venue.organization, venue=venue, policy=old
        ).user
        booking = _book(member, venue, _class(venue), "gf-1")

        cancel_booking(member, booking)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED

    def test_unpinned_member_follows_current(self):
        venue = VenueFactory()
        VenuePolicy.objects.activate(venue, class_late_cancel_hours=72)
        VenuePolicy.objects.activate(venue, class_late_cancel_hours=8)
        member = MembershipFactory(organization=venue.organization, venue=venue).user
        booking = _book(member, venue, _class(venue, days=0.1), "cur-1")

        cancel_booking(member, booking)

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED_LATE
