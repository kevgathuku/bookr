"""E2E dataset: fixed e2e-run org with known credentials and sessions the
smoke suite touches. Re-runnable by construction; invoked directly as
`manage.py seed_e2e` (boot.sh, pytest fixture)."""

import contextlib

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from access.models import AccessEvent, AccessPoint
from organizations.management.seed_helpers import (
    booker_membership,
    ensure_org_role,
    seed_new_graph,
    try_book,
)
from organizations.models import Organization, OrgRole, Venue


class Command(BaseCommand):
    help = "Seed the fixed e2e-run org. Re-runnable."

    def handle(self, *args, **options):
        _e2e_org()
        self.stdout.write(
            self.style.SUCCESS("Seeded e2e-run org (e2e-run-member / password).")
        )


_PEOPLE_SPECS = (
    ("teacher", "e2e-run-teacher", OrgRole.Role.TEACHER),
    ("member", "e2e-run-member", OrgRole.Role.MEMBER),
    ("stranger", "e2e-run-stranger", OrgRole.Role.MEMBER),
    ("booker", "e2e-run-booker", OrgRole.Role.MEMBER),
    ("frontdesk", "e2e-run-frontdesk", OrgRole.Role.FRONTDESK),
)


def _e2e_people(org):
    users = {}
    for key, username, role in _PEOPLE_SPECS:
        user = get_user_model().objects.get_or_create(username=username)[0]
        user.set_password("password")
        user.save()
        ensure_org_role(org, user, role)
        users[key] = user
    return users


def _e2e_org():
    org = Organization.objects.get_or_create(
        slug="e2e-run", defaults={"name": "E2E Run"}
    )[0]
    venue = Venue.objects.get_or_create(
        organization=org,
        slug="main",
        defaults={"name": "Main", "time_zone": "Africa/Nairobi"},
    )[0]
    if venue.time_zone == "UTC":
        venue.time_zone = "Africa/Nairobi"
        venue.save(update_fields=["time_zone"])
    annex = Venue.objects.get_or_create(
        organization=org,
        slug="annex",
        defaults={"name": "Annex", "time_zone": "Africa/Nairobi"},
    )[0]
    people = _e2e_people(org)
    _seed_memberships(venue, people)
    session = seed_new_graph(venue, people)
    try_book(people["booker"], session)
    _seed_door(venue, people)
    _seed_annex_session(annex, people)


def _seed_memberships(venue, people):
    booker_membership(venue, people["booker"])
    booker_membership(venue, people["member"])


def _seed_door(venue, people):
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


def _seed_annex_session(annex, people):
    from scheduling.catalogue import ClassCategory, ClassOffering

    offering, _ = ClassOffering.objects.get_or_create(
        venue=annex,
        teacher=people["teacher"],
        title="Yoga",
        category=ClassCategory.GROUP,
        defaults={"duration_minutes": 60, "credit_cost": 1},
    )
    from django.core.exceptions import ValidationError

    from scheduling.sessions import schedule_session

    start = timezone.now() + timezone.timedelta(days=1)
    if not offering.sessions.filter(starts_at__gt=timezone.now()).exists():
        with contextlib.suppress(ValidationError):
            schedule_session(offering=offering, starts_at=start)
