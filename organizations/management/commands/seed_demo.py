import contextlib

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from organizations.models import Membership, Organization, Venue, VenuePolicy

# Demo cast: fixed usernames (password "password" for all), so the README
# can name every login and each one works straight after seeding.
# Re-runnable via get_or_create throughout; exact-start classes never dup.


def _demo_user(username):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.com"},
    )
    if created:
        user.set_password("password")  # dev seed only — never in prod
        user.save()
    return user


def _membership(org, user, role, venue=None):
    Membership.objects.get_or_create(
        organization=org, venue=venue, user=user, defaults={"role": role}
    )


def _room(venue, name, capacity):
    from scheduling.models import Room

    room, _ = Room.objects.get_or_create(
        venue=venue, name=name, defaults={"capacity": capacity}
    )
    if room.capacity != capacity:
        room.capacity = capacity
        room.save(update_fields=["capacity"])
    return room


def _schedule(venue, teacher, class_name, room_name, capacity=20):
    from datetime import timedelta

    from django.utils import timezone

    from scheduling.models import ClassType, ScheduledClass

    VenuePolicy.objects.get_or_create(venue=venue, valid_until=None)
    class_type = ClassType.objects.get_or_create(
        venue=venue,
        name=class_name,
        defaults={"duration_min": 45},
    )[0]
    room = _room(venue, room_name, capacity)
    start = timezone.now() + timedelta(days=1)
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


def _next_weekday(now, weekday, hour, minute=0):
    from datetime import timedelta

    start = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if start <= now:
        start += timedelta(days=7)
    return start


def _weekly(venue, teacher, class_name, room_name, weekdays, hour, capacity=20):
    """One class on each listed weekday (0=Monday), next occurrence onward."""
    from datetime import timedelta

    from django.utils import timezone

    from scheduling.models import ClassType, ScheduledClass

    VenuePolicy.objects.get_or_create(venue=venue, valid_until=None)
    class_type = ClassType.objects.get_or_create(
        venue=venue,
        name=class_name,
        defaults={"duration_min": 60},
    )[0]
    room = _room(venue, room_name, capacity)
    ScheduledClass.objects.filter(
        venue=venue, room=room, starts_at__lte=timezone.now()
    ).delete()
    made = []
    for weekday in weekdays:
        start = _next_weekday(timezone.now(), weekday, hour)
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


def _passes(product_venue, name, credits, members):
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


def _book(member, klass, key):
    from booking.errors import DuplicateBooking, SeatFull
    from booking.services import book_seat

    with contextlib.suppress(DuplicateBooking, SeatFull):
        book_seat(member, klass, idempotency_key=key)


def _spanning_org():
    org, _ = Organization.objects.get_or_create(
        slug="downtown-dance", defaults={"name": "Downtown Dance"}
    )  # SPANNING default
    main, _ = Venue.objects.get_or_create(
        organization=org,
        slug="main",
        defaults={"name": "Main Studio", "time_zone": "America/New_York"},
    )
    annex, _ = Venue.objects.get_or_create(
        organization=org,
        slug="annex",
        defaults={"name": "Annex", "time_zone": "America/New_York"},
    )
    cast = {
        "owner": Membership.Role.OWNER,
        "manager": Membership.Role.MANAGER,
        "teacher": Membership.Role.TEACHER,
        "frontdesk": Membership.Role.FRONTDESK,
        "member": Membership.Role.MEMBER,
        "member2": Membership.Role.MEMBER,
    }
    users = {}
    for key, role in cast.items():
        user = _demo_user(f"demo-{key}")
        _membership(org, user, role)
        users[key] = user
    spin = _weekly(main, users["teacher"], "Spin", "Main Room", [0, 2, 4], 7)
    _weekly(main, users["teacher"], "Yoga", "Studio", [1, 3], 18)
    tiny = _schedule(annex, users["teacher"], "Tiny", "Closet", capacity=1)
    _passes(main, "Dance 10-Class Pack", 10, [users["member"], users["member2"]])
    _book(users["member2"], tiny, "demo-seed-tiny")
    _book(users["member"], spin[0], "demo-seed-spin")


def _per_venue_org():
    org, _ = Organization.objects.get_or_create(
        slug="uptown-box",
        defaults={
            "name": "Uptown Box",
            "membership_scope": Organization.Scope.PER_VENUE,
        },
    )
    box, _ = Venue.objects.get_or_create(
        organization=org,
        slug="box",
        defaults={"name": "The Box", "time_zone": "America/Chicago"},
    )
    annex, _ = Venue.objects.get_or_create(
        organization=org,
        slug="annex",
        defaults={"name": "Annex Box", "time_zone": "America/Chicago"},
    )
    pinned = _demo_user("demo-pinned")
    _membership(org, pinned, Membership.Role.MEMBER, box)
    coach = _demo_user("demo-coach")
    _membership(org, coach, Membership.Role.TEACHER, annex)
    klass = _schedule(box, coach, "Box", "The Floor")
    _schedule(annex, coach, "Box", "The Floor")
    _passes(box, "Box 5-Class Pack", 5, [pinned])
    _book(pinned, klass, "demo-seed-box")


class Command(BaseCommand):
    help = "Seed a demo org pair: one spanning, one per-venue. Re-runnable."

    def add_arguments(self, parser):
        parser.add_argument(
            "--e2e",
            action="store_true",
            help="Also seed the fixed e2e-run org (known users, short windows).",
        )
        parser.add_argument(
            "--e2e-only",
            action="store_true",
            help="Seed only the e2e-run org (no demo users).",
        )

    def handle(self, *args, **options):
        if options["e2e_only"]:
            call_command("seed_e2e")
            return
        _spanning_org()
        _per_venue_org()
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded downtown-dance + uptown-box: demo-owner, "
                "demo-manager, demo-teacher, demo-frontdesk, demo-member, "
                "demo-member2, demo-pinned, demo-coach / password"
            )
        )
        if options["e2e"]:
            call_command("seed_e2e")
