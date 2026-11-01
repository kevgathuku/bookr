"""Shared seed builders for the management commands.

Demo cast uses fixed usernames (password "password" for all), so the README
can name every login and each one works straight after seeding.
Re-runnable via get_or_create throughout.
"""

import contextlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone


def create_user(username):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.com"},
    )
    if created:
        user.set_password("password")  # dev seed only — never in prod
        user.save()
    return user


def ensure_org_role(org, user, role, venue=None):
    from organizations.models import OrgRole

    OrgRole.objects.get_or_create(organization=org, venue=venue, user=user, role=role)


def class_days_out():
    """Days out so the class lands inside the displayed week.

    The calendar shows the current week; plain "+1 day" falls into next
    week on Saturdays, leaving an empty grid. Seed later today instead.
    """
    if timezone.now().weekday() == 5:  # Saturday
        return 0.2  # ~5h out: still future and bookable, still this week
    return 1


def next_weekday(now, weekday, hour, minute=0):
    start = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if start <= now:
        start += timedelta(days=7)
    return start


def seed_sessions(venue, teacher, title, category, weekdays, hour, capacity=20):
    """One offering plus next occurrence per weekday, via the real service."""
    from scheduling.models import ClassOffering
    from scheduling.sessions import schedule_session

    offering, _ = ClassOffering.objects.get_or_create(
        venue=venue,
        teacher=teacher,
        title=title,
        category=category,
        defaults={"duration_minutes": 60, "credit_cost": 1},
    )
    made = []
    for weekday in weekdays:
        start = next_weekday(timezone.now(), weekday, hour)
        existing = offering.sessions.filter(starts_at=start).first()
        if existing is not None:
            made.append(existing)
            continue
        with contextlib.suppress(ValidationError):
            made.append(
                schedule_session(offering=offering, starts_at=start, capacity=capacity)
            )
    return offering, made


def try_book(member, session):
    from booking.errors import DuplicateBooking, SeatFull
    from booking.services import book_session

    with contextlib.suppress(DuplicateBooking, SeatFull):
        book_session(member=member, session=session)


def seed_new_graph(venue, people):
    """New-catalogue rows the calendar serves: one offering + one session."""
    from scheduling.models import ClassCategory, ClassOffering, ClassSession

    offering, _ = ClassOffering.objects.get_or_create(
        venue=venue,
        teacher=people["teacher"],
        title="Spin",
        category=ClassCategory.GROUP,
        defaults={"duration_minutes": 60, "credit_cost": 1},
    )
    start = timezone.now() + timedelta(days=class_days_out())
    session = ClassSession.objects.filter(
        offering=offering, starts_at__gt=timezone.now()
    ).first()
    if session is None:
        session = ClassSession.objects.create(offering=offering, starts_at=start)
    return session


def booker_membership(venue, user, name="Credits", credits=10, validity_days=30):
    """Get-or-create a credit-pack membership for API/seed booking flows."""
    from passes.models import Membership as PlanMembership
    from passes.models import Plan, PlanType

    plan, _ = Plan.objects.get_or_create(
        organization=venue.organization,
        name=name,
        defaults={"plan_type": PlanType.CREDIT_PACK, "validity_days": validity_days},
    )
    membership, _ = PlanMembership.objects.get_or_create(
        user=user,
        plan=plan,
        defaults={
            "credits_remaining": credits,
            "starts_on": timezone.now().date(),
            "ends_on": timezone.now().date() + timedelta(days=validity_days),
        },
    )
    return membership
