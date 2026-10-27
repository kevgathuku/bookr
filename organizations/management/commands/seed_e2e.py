"""E2E dataset: fixed e2e-run org with known credentials, short windows,
and one of every model the smoke suite touches. Re-runnable by construction
(get_or_create + stale-class sweep); invoked via seed_demo --e2e."""

import contextlib
from datetime import time as dtime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from access.models import AccessEvent, AccessPoint
from booking.errors import DuplicateBooking, SeatFull
from booking.services import book_seat
from organizations.management.commands.seed_demo import _membership, _schedule
from organizations.models import Membership, Organization, Venue, VenuePolicy
from passes.models import PassProduct
from passes.services import adjust_credit, issue_pass
from scheduling.appointments import Appointment, AvailabilityRule, Resource
from scheduling.models import TeacherSubstitution


class Command(BaseCommand):
    help = "Seed the fixed e2e-run org. Re-runnable."

    def handle(self, *args, **options):
        _e2e_org()
        self.stdout.write(
            self.style.SUCCESS("Seeded e2e-run org (e2e-run-member / password).")
        )


def _named_user(username):
    user, created = get_user_model().objects.get_or_create(username=username)
    if created:
        user.set_password("password")
        user.save()
    return user


def _e2e_people(org):
    teacher = _named_user("e2e-run-teacher")
    _membership(org, teacher, Membership.Role.TEACHER)
    member = _named_user("e2e-run-member")
    _membership(org, member, Membership.Role.MEMBER)
    stranger = _named_user("e2e-run-stranger")
    _membership(org, stranger, Membership.Role.MEMBER)
    return {"teacher": teacher, "member": member, "stranger": stranger}


def _e2e_org():
    org = Organization.objects.get_or_create(
        slug="e2e-run", defaults={"name": "E2E Run"}
    )[0]
    venue = Venue.objects.get_or_create(
        organization=org, slug="main", defaults={"name": "Main"}
    )[0]
    VenuePolicy.objects.update_or_create(
        venue=venue,
        valid_until=None,
        defaults={"waitlist_hold_minutes": 1},
    )
    people = _e2e_people(org)
    product = PassProduct.objects.get_or_create(
        venue=venue,
        name="E2E Pack",
        defaults={"credits_total": 10, "validity_days": 30},
    )[0]
    member = people["member"]
    if not member.passes.exists():
        issue_pass(member, product)
    _seed_extras(
        venue,
        org,
        people,
        product,
        _schedule(venue, people["teacher"], "Spin", "Main Room"),
    )


def _seed_bookings(venue, people, klass, resource, product):
    member = people["member"]
    booker = _named_user("e2e-run-booker")
    _membership(venue.organization, booker, Membership.Role.MEMBER)
    if not booker.passes.exists():
        issue_pass(booker, product)
    Appointment.objects.filter(
        venue=venue, teacher=people["teacher"], starts_at__lte=timezone.now()
    ).delete()
    appt_start = timezone.now() + timezone.timedelta(days=2)
    existing = Appointment.objects.filter(
        venue=venue, teacher=people["teacher"], starts_at__gt=timezone.now()
    ).first()
    if existing is None:
        Appointment.objects.create(
            venue=venue,
            member=member,
            teacher=people["teacher"],
            resource=resource,
            starts_at=appt_start,
            ends_at=appt_start + timezone.timedelta(hours=1),
        )
    with contextlib.suppress(DuplicateBooking, SeatFull):
        book_seat(booker, klass, idempotency_key="e2e-seed-book")
    member_pass = member.passes.first()
    if member_pass is not None:
        adjust_credit(member_pass, 1, "e2e goodwill", people["teacher"])


def _seed_paperwork(venue, org, people, klass):
    sub = _named_user("e2e-run-sub")
    _membership(org, sub, Membership.Role.TEACHER)
    TeacherSubstitution.objects.get_or_create(
        scheduled_class=klass,
        new_teacher=sub,
        defaults={"old_teacher": people["teacher"], "reason": "e2e cover"},
    )
    point = AccessPoint.objects.get_or_create(
        venue=venue, controller_id="e2e-door", defaults={"name": "E2E Door"}
    )[0]
    if not AccessEvent.objects.filter(access_point=point).exists():
        AccessEvent.objects.create(
            access_point=point,
            member=people["member"],
            granted=True,
            reason="active_pass",
        )
        AccessEvent.objects.create(
            access_point=point, member=None, granted=False, reason="no_access"
        )


def _seed_extras(venue, org, people, product, klass):
    """Models the demo pair skips: appointments, bookings, subs, events."""
    resource = Resource.objects.get_or_create(
        venue=venue, name="Physio Table", defaults={"type": "equipment"}
    )[0]
    AvailabilityRule.objects.get_or_create(
        resource=resource,
        weekday=0,
        defaults={"start_time": dtime(9, 0), "end_time": dtime(17, 0)},
    )
    _seed_bookings(venue, people, klass, resource, product)
    _seed_paperwork(venue, org, people, klass)
