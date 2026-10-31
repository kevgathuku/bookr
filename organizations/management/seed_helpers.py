"""Shared seed builders for the management commands.

Demo cast uses fixed usernames (password "password" for all), so the README
can name every login and each one works straight after seeding.
Re-runnable via get_or_create throughout; exact-start classes never dup.
"""

import contextlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from organizations.models import Membership, VenuePolicy


def demo_user(username):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.com"},
    )
    if created:
        user.set_password("password")  # dev seed only — never in prod
        user.save()
    return user


def ensure_membership(org, user, role, venue=None):
    Membership.objects.get_or_create(
        organization=org, venue=venue, user=user, defaults={"role": role}
    )


def ensure_room(venue, name, capacity):
    from scheduling.models import Room

    room, _ = Room.objects.get_or_create(
        venue=venue, name=name, defaults={"capacity": capacity}
    )
    if room.capacity != capacity:
        room.capacity = capacity
        room.save(update_fields=["capacity"])
    return room


def class_days_out():
    """Days out so the class lands inside the displayed Sunday-start week.

    The calendar shows the current week; plain "+1 day" falls into next
    week on Saturdays, leaving an empty grid. Seed later today instead.
    """
    if timezone.now().weekday() == 5:  # Saturday
        return 0.2  # ~5h out: still future and bookable, still this week
    return 1


def schedule_class(venue, teacher, class_name, room_name, capacity=20, days=1):
    from scheduling.models import ClassType, ScheduledClass

    VenuePolicy.objects.get_or_create(venue=venue, valid_until=None)
    class_type = ClassType.objects.get_or_create(
        venue=venue,
        name=class_name,
        defaults={"duration_min": 45},
    )[0]
    room = ensure_room(venue, room_name, capacity)
    start = timezone.now() + timedelta(days=days)
    # Re-runnable: drop this room's stale classes, keep one fresh slot.
    ScheduledClass.objects.filter(
        venue=venue, room=room, starts_at__lte=timezone.now()
    ).delete()
    fresh = ScheduledClass.objects.filter(
        venue=venue, room=room, starts_at__gt=timezone.now()
    ).first()
    if fresh is not None:
        return fresh
    return ScheduledClass.objects.get_or_create(
        venue=venue,
        room=room,
        teacher=teacher,
        starts_at=start,
        defaults={"class_type": class_type, "ends_at": start + timedelta(hours=1)},
    )[0]


def next_weekday(now, weekday, hour, minute=0):
    start = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if start <= now:
        start += timedelta(days=7)
    return start


def schedule_weekly(venue, teacher, class_name, room_name, weekdays, hour, capacity=20):
    """One class on each listed weekday (0=Monday), next occurrence onward."""
    from scheduling.models import ClassType, ScheduledClass

    VenuePolicy.objects.get_or_create(venue=venue, valid_until=None)
    class_type = ClassType.objects.get_or_create(
        venue=venue,
        name=class_name,
        defaults={"duration_min": 60},
    )[0]
    room = ensure_room(venue, room_name, capacity)
    ScheduledClass.objects.filter(
        venue=venue, room=room, starts_at__lte=timezone.now()
    ).delete()
    made = []
    for weekday in weekdays:
        start = next_weekday(timezone.now(), weekday, hour)
        klass, _ = ScheduledClass.objects.get_or_create(
            venue=venue,
            room=room,
            teacher=teacher,
            starts_at=start,
            defaults={
                "class_type": class_type,
                "ends_at": start + timedelta(hours=1),
            },
        )
        made.append(klass)
    return made


def grant_passes(product_venue, name, credits, members):
    from passes.models import PassProduct
    from passes.services import issue_pass

    product, _ = PassProduct.objects.get_or_create(
        venue=product_venue,
        name=name,
        defaults={"credits_total": credits, "validity_days": 30},
    )
    for member in members:
        if not member.passes.exists():
            issue_pass(member, product)
    return product


def try_book(member, klass, key):
    from booking.errors import DuplicateBooking, SeatFull
    from booking.services import book_seat

    with contextlib.suppress(DuplicateBooking, SeatFull):
        book_seat(member, klass, idempotency_key=key)
