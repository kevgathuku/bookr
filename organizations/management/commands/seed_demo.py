# Demo cast: fixed usernames (password "password" for all), so the README
# can name every login and each one works straight after seeding.
# Re-runnable via get_or_create throughout; exact-start classes never dup.
from django.core.management import call_command
from django.core.management.base import BaseCommand

from organizations.management.seed_helpers import (
    demo_user,
    ensure_membership,
    grant_passes,
    schedule_class,
    schedule_weekly,
    try_book,
)
from organizations.models import Membership, Organization, Venue


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
        user = demo_user(f"demo-{key}")
        ensure_membership(org, user, role)
        users[key] = user
    spin = schedule_weekly(main, users["teacher"], "Spin", "Main Room", [0, 2, 4], 7)
    schedule_weekly(main, users["teacher"], "Yoga", "Studio", [1, 3], 18)
    tiny = schedule_class(annex, users["teacher"], "Tiny", "Closet", capacity=1)
    grant_passes(main, "Dance 10-Class Pack", 10, [users["member"], users["member2"]])
    try_book(users["member2"], tiny, "demo-seed-tiny")
    try_book(users["member"], spin[0], "demo-seed-spin")


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
    pinned = demo_user("demo-pinned")
    ensure_membership(org, pinned, Membership.Role.MEMBER, box)
    coach = demo_user("demo-coach")
    ensure_membership(org, coach, Membership.Role.TEACHER, annex)
    klass = schedule_class(box, coach, "Box", "The Floor")
    schedule_class(annex, coach, "Box", "The Floor")
    grant_passes(box, "Box 5-Class Pack", 5, [pinned])
    try_book(pinned, klass, "demo-seed-box")


def _remodel_graph():
    """New-domain rows for the demo orgs. Re-runnable via get_or_create."""
    from datetime import timedelta

    from django.utils import timezone

    from booking.models import CancellationPolicy
    from organizations.models import OrgRole
    from passes.models import (
        CreditLedger,
        MembershipPlan,
        PlanType,
    )
    from passes.models import (
        Membership as PlanMembership,
    )
    from scheduling.catalogue import ClassCategory, ClassOffering, ClassSession

    org = Organization.objects.get(slug="downtown-dance")
    main = Venue.objects.get(organization=org, slug="main")
    teacher = demo_user("demo-teacher")
    OrgRole.objects.get_or_create(
        organization=org,
        venue=main,
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
    plan, _ = MembershipPlan.objects.get_or_create(
        organization=org,
        name="Dance 10-Class Pack",
        defaults={"plan_type": PlanType.CREDIT_PACK, "validity_days": 30},
    )
    for username in ("demo-member", "demo-member2"):
        user = demo_user(username)
        membership, created = PlanMembership.objects.get_or_create(
            user=user,
            plan=plan,
            defaults={
                "credits_remaining": 10,
                "starts_on": timezone.now().date(),
            },
        )
        if created:
            CreditLedger.objects.create(
                membership=membership,
                delta=10,
                reason=CreditLedger.Reason.PURCHASE,
            )
    offering, _ = ClassOffering.objects.get_or_create(
        venue=main,
        teacher=teacher,
        title="Spin",
        category=ClassCategory.GROUP,
        defaults={"duration_minutes": 60, "credit_cost": 1},
    )
    ClassSession.objects.filter(
        offering=offering, starts_at__lte=timezone.now()
    ).delete()
    if not ClassSession.objects.filter(
        offering=offering, starts_at__gt=timezone.now()
    ).exists():
        ClassSession.objects.create(
            offering=offering, starts_at=timezone.now() + timedelta(days=1)
        )


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
