from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from faker import Faker

from organizations.models import Membership, Organization, Venue, VenuePolicy

# Seeded: same names every run, so get_or_create keeps this command re-runnable.
Faker.seed(42)
fake = Faker()


def _user():
    User = get_user_model()
    username = fake.unique.user_name()
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@example.com",
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
        },
    )
    if created:
        user.set_password("password")  # dev seed only — never in prod
        user.save()
    return user


def _membership(org, user, role, venue=None):
    Membership.objects.get_or_create(
        organization=org, venue=venue, user=user, defaults={"role": role}
    )


def _schedule(venue, teacher, class_name, room_name):
    from datetime import timedelta

    from django.utils import timezone

    from scheduling.models import ClassType, Room, ScheduledClass

    VenuePolicy.objects.get_or_create(venue=venue, valid_until=None)
    class_type = ClassType.objects.get_or_create(
        venue=venue,
        name=class_name,
        defaults={"duration_min": 45},
    )[0]
    room = Room.objects.get_or_create(
        venue=venue,
        name=room_name,
        defaults={"capacity": 20},
    )[0]
    start = timezone.now() + timedelta(days=1)
    ScheduledClass.objects.get_or_create(
        venue=venue,
        room=room,
        teacher=teacher,
        starts_at=start,
        defaults={"class_type": class_type, "ends_at": start + timedelta(hours=1)},
    )


def _spanning_org():
    org_a, _ = Organization.objects.get_or_create(
        slug="downtown-dance", defaults={"name": "Downtown Dance"}
    )  # SPANNING default
    venue_a1, _ = Venue.objects.get_or_create(
        organization=org_a,
        slug="main",
        defaults={"name": "Main Studio", "time_zone": "America/New_York"},
    )
    venue_a2, _ = Venue.objects.get_or_create(
        organization=org_a,
        slug="annex",
        defaults={"name": "Annex", "time_zone": "America/New_York"},
    )
    teacher_a = _user()
    _membership(org_a, teacher_a, Membership.Role.TEACHER)
    spanning = _user()
    _membership(org_a, spanning, Membership.Role.MEMBER)
    _schedule(venue_a1, teacher_a, "Spin", "Main Room")
    _schedule(venue_a2, teacher_a, "Yoga", "Annex Room")
    return spanning


def _per_venue_org():
    org_b, _ = Organization.objects.get_or_create(
        slug="uptown-box",
        defaults={
            "name": "Uptown Box",
            "membership_scope": Organization.Scope.PER_VENUE,
        },
    )
    venue_b1, _ = Venue.objects.get_or_create(
        organization=org_b,
        slug="box",
        defaults={"name": "The Box", "time_zone": "America/Chicago"},
    )
    venue_b2, _ = Venue.objects.get_or_create(
        organization=org_b,
        slug="annex",
        defaults={"name": "Annex Box", "time_zone": "America/Chicago"},
    )
    pinned = _user()
    _membership(org_b, pinned, Membership.Role.MEMBER, venue_b1)
    teacher = _user()
    _membership(org_b, teacher, Membership.Role.TEACHER, venue_b2)
    _schedule(venue_b1, teacher, "Box", "The Floor")
    _schedule(venue_b2, teacher, "Box", "The Floor")
    return pinned, teacher


class Command(BaseCommand):
    help = "Seed a demo org pair: one spanning, one per-venue. Re-runnable."

    def handle(self, *args, **options):
        spanning = _spanning_org()
        pinned, teacher = _per_venue_org()
        message = (
            f"Seeded: {spanning.username} spans A1+A2, "
            f"{pinned.username} pinned to B1, "
            f"{teacher.username} teaches B2"
        )
        self.stdout.write(self.style.SUCCESS(message))
