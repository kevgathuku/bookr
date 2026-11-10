# Demo cast: fixed usernames (password "password" for all), so the README
# can name every login and each one works straight after seeding.
# Re-runnable via get_or_create throughout.
from django.core.management import call_command
from django.core.management.base import BaseCommand

from organizations.management.seed_helpers import (
    create_user,
    ensure_org_role,
    seed_sessions,
)
from organizations.models import Organization, OrgRole, Venue
from scheduling.models import ClassCategory


def _spanning_org():
    org, _ = Organization.objects.get_or_create(
        slug="downtown-dance", defaults={"name": "Downtown Dance"}
    )  # SPANNING default
    main, _ = Venue.objects.get_or_create(
        organization=org,
        slug="main",
        defaults={"name": "Main Studio", "time_zone": "America/New_York"},
    )
    Venue.objects.get_or_create(
        organization=org,
        slug="annex",
        defaults={"name": "Annex", "time_zone": "America/New_York"},
    )
    # Annex stays session-free in the demo; it exists for the venue switcher.
    cast = {
        "owner": OrgRole.Role.OWNER,
        "manager": OrgRole.Role.MANAGER,
        "teacher": OrgRole.Role.TEACHER,
        "frontdesk": OrgRole.Role.FRONTDESK,
        "member": OrgRole.Role.MEMBER,
        "member2": OrgRole.Role.MEMBER,
    }
    users = {}
    for key, role in cast.items():
        user = create_user(f"demo-{key}")
        ensure_org_role(org, user, role)
        users[key] = user
    seed_sessions(main, users["teacher"], "Spin", ClassCategory.GROUP, [0, 2, 4], 7)
    seed_sessions(main, users["teacher"], "Yoga", ClassCategory.GROUP, [1, 3], 18)


def _per_venue_org():
    org, _ = Organization.objects.get_or_create(
        slug="uptown-box",
        defaults={
            "name": "Uptown Box",
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
    pinned = create_user("demo-pinned")
    ensure_org_role(org, pinned, OrgRole.Role.MEMBER, box)
    coach = create_user("demo-coach")
    ensure_org_role(org, coach, OrgRole.Role.TEACHER, annex)
    # Coach teaches at both venues, so the role must cover box too:
    # offering save() validates the teacher role and is not suppressed.
    ensure_org_role(org, coach, OrgRole.Role.TEACHER, box)
    seed_sessions(box, coach, "Box", ClassCategory.GROUP, [0, 2, 4], 7, capacity=20)
    seed_sessions(annex, coach, "Box", ClassCategory.GROUP, [1, 3], 18)


def _remodel_graph():
    """New-domain rows for the demo orgs. Re-runnable via get_or_create."""
    _remodel_spot(
        org_slug="downtown-dance",
        venue_slug="main",
        teacher_username="demo-teacher",
        plan_name="Dance 10-Class Pack",
        roster={"demo-member": 10, "demo-member2": 10},
        book_all=True,
    )
    _remodel_spot(
        org_slug="uptown-box",
        venue_slug="box",
        teacher_username="demo-coach",
        plan_name="Box 5-Class Pack",
        roster={"demo-pinned": 5},
        book_all=True,
    )


def _remodel_spot(org_slug, venue_slug, teacher_username, plan_name, roster, book_all):
    """New-domain rows for one demo venue: plan, memberships, offering, session."""
    from contextlib import suppress
    from datetime import timedelta

    from django.utils import timezone

    from booking.errors import DuplicateBooking, SeatFull
    from booking.models import CancellationPolicy
    from booking.services import book_session
    from organizations.models import OrgRole
    from passes.models import CreditLedger, Entitlement, Plan, PlanType, Validity
    from passes.models import Membership as PlanMembership
    from scheduling.models import ClassCategory, ClassOffering, ClassSession

    org = Organization.objects.get(slug=org_slug)
    venue = Venue.objects.get(organization=org, slug=venue_slug)
    teacher = create_user(teacher_username)
    OrgRole.objects.get_or_create(
        organization=org,
        venue=venue,
        user=teacher,
        role=OrgRole.Role.TEACHER,
    )

    CancellationPolicy.objects.get_or_create(
        organization=org,
        venue=None,
        class_category=None,
        plan_type=None,
        defaults={
            "late_cancel_hours": 12,
            "enforcement": CancellationPolicy.Enforcement.NONE,
        },
    )
    plan, _ = Plan.objects.get_or_create(
        organization=org,
        name=plan_name,
        defaults={
            "plan_type": PlanType.CREDIT_PACK,
            "entitlement": Entitlement.CREDITS,
            "credits_included": 10,
            "validity": Validity.FIXED_DURATION,
            "duration_days": 30,
        },
    )
    users = {}
    today = timezone.now().date()
    for username, credits in roster.items():
        user = create_user(username)
        users[username] = user
        # Boot seeding re-runs on every cold start: one membership per
        # user+plan, or demo credits grow on each restart.
        if PlanMembership.objects.filter(user=user, plan=plan).exists():
            continue
        membership = PlanMembership.objects.create(
            user=user,
            plan=plan,
            credits_remaining=credits,
            starts_on=today,
            valid_until=today + timedelta(days=30),
        )
        CreditLedger.objects.create(
            membership=membership,
            delta=credits,
            reason=CreditLedger.Reason.PURCHASE,
        )
    offering, _ = ClassOffering.objects.get_or_create(
        venue=venue,
        teacher=teacher,
        title="Spin",
        category=ClassCategory.GROUP,
        defaults={"duration_minutes": 60, "credit_cost": 1},
    )
    ClassSession.objects.filter(
        offering=offering, starts_at__lte=timezone.now()
    ).delete()
    session = ClassSession.objects.filter(
        offering=offering, starts_at__gt=timezone.now()
    ).first()
    if session is None:
        session = ClassSession.objects.create(
            offering=offering, starts_at=timezone.now() + timedelta(days=1)
        )
    if book_all:
        for user in users.values():
            with suppress(DuplicateBooking, SeatFull):
                book_session(member=user, session=session)


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
        _remodel_graph()
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded downtown-dance + uptown-box: demo-owner, "
                "demo-manager, demo-teacher, demo-frontdesk, demo-member, "
                "demo-member2, demo-pinned, demo-coach / password"
            )
        )
        if options["e2e"]:
            call_command("seed_e2e")
