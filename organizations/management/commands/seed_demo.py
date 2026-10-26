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


class Command(BaseCommand):
    help = "Seed a demo org pair: one spanning, one per-venue. Re-runnable."

    def handle(self, *args, **options):
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
        for venue in (venue_a1, venue_a2, venue_b1, venue_b2):
            VenuePolicy.objects.get_or_create(venue=venue, valid_until=None)

        spanning = _user()
        _membership(org_a, spanning, Membership.Role.MEMBER)
        pinned = _user()
        _membership(org_b, pinned, Membership.Role.MEMBER, venue_b1)
        teacher = _user()
        _membership(org_b, teacher, Membership.Role.TEACHER, venue_b2)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded: {spanning.username} spans A1+A2, {pinned.username} pinned to B1, "
                f"{teacher.username} teaches B2"
            )
        )
