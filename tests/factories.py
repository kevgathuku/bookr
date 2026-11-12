from collections.abc import Iterable
from datetime import timedelta

import factory
from django.contrib.auth import get_user_model
from django.template.defaultfilters import slugify
from django.utils import timezone
from faker import Faker

from aggregators.models import Aggregator
from aggregators.tokens import new_token
from booking.models import CancellationPolicy
from organizations.models import Organization, OrgRole, Venue
from passes.models import (
    CreditLedger,
    Entitlement,
    Plan,
    PlanType,
    Validity,
)
from passes.models import (
    Membership as PlanMembership,
)
from scheduling.models import ClassCategory, ClassOffering, ClassSession

fake = Faker()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        # evaluated at import; fine under test setup
        model = get_user_model()
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@example.com")

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        """Known login password for every factory user (e2e login, auth flows)."""
        if not create:
            return
        obj.set_password(extracted or "password")
        obj.save(update_fields=["password"])


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"{fake.company()} {n}")
    slug = factory.LazyAttribute(lambda org: slugify(org.name))


class VenueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Venue

    organization = factory.SubFactory(OrganizationFactory)
    slug = factory.Sequence(lambda n: f"venue-{n}")
    name = factory.Sequence(lambda n: f"Venue {n}")


class OrgRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrgRole

    # org-wide default; venue-pinned callers pass venue explicitly.
    # Organization derives from the venue so the factory always builds a
    # coherent row (save() runs full_clean); pass organization explicitly
    # only for org-wide roles or the cross-org rejection test.
    venue = None
    organization = factory.LazyAttribute(
        lambda role: role.venue.organization if role.venue else OrganizationFactory()
    )
    user = factory.SubFactory(UserFactory)
    role = OrgRole.Role.MEMBER


class ClassOfferingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClassOffering
        # teacher_role only creates the linked OrgRole; the offering itself
        # needs no post-hook save (and factory_boy will stop saving by
        # default in the next major release).
        skip_postgeneration_save = True

    venue = factory.SubFactory(VenueFactory)
    teacher = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Offering {n}")
    category = ClassCategory.GROUP
    duration = timedelta(minutes=60)
    credit_cost = 1

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Role before save: offering.save() enforces the covering-teacher
        # invariant, and post-generation hooks run too late to satisfy it.
        teacher = kwargs.get("teacher")
        venue = kwargs.get("venue")
        if (
            teacher is not None
            and venue is not None
            and getattr(teacher, "pk", None)
            and getattr(venue, "pk", None)
        ):
            OrgRole.objects.get_or_create(
                organization=venue.organization,
                venue=venue,
                user=teacher,
                role=OrgRole.Role.TEACHER,
            )
        return super()._create(model_class, *args, **kwargs)


class ClassSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClassSession

    offering = factory.SubFactory(ClassOfferingFactory)
    starts_at = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=1),
    )


class CancellationPolicyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CancellationPolicy

    organization = factory.SubFactory(OrganizationFactory)
    late_cancel_hours = 12
    enforcement = CancellationPolicy.Enforcement.NONE


class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan

    class Params:
        monthly = factory.Trait(
            plan_type=PlanType.MONTHLY,
            entitlement=Entitlement.UNLIMITED,
            credits_included=None,
            validity=Validity.RECURRING,
        )

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Plan {n}")
    plan_type = PlanType.CREDIT_PACK
    entitlement = Entitlement.CREDITS
    credits_included = 10
    validity = Validity.FIXED_DURATION
    duration_days = 30


class PlanMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlanMembership

    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(PlanFactory)
    credits_remaining = 0
    starts_on = factory.LazyFunction(lambda: timezone.now().date())
    valid_until = factory.LazyAttribute(
        lambda membership: (
            None
            if membership.plan.duration_days is None
            else membership.starts_on + timedelta(days=membership.plan.duration_days)
        )
    )
    payment_ref = ""


class CreditLedgerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CreditLedger

    membership = factory.SubFactory(PlanMembershipFactory)
    delta = 1
    reason = CreditLedger.Reason.PURCHASE


class AggregatorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Aggregator

    slug = factory.Sequence(lambda n: f"aggregator-{n}")
    name = factory.LazyAttribute(lambda partner: partner.slug.title())
    api_token_hash = factory.LazyAttribute(lambda _partner: new_token()[1])
    seat_allotment = 4
    service_user = factory.SubFactory(UserFactory)


def user_with_roles(
    venue: Venue,
    roles: Iterable[tuple[OrgRole.Role, bool]],
    username: str | None = None,
    staff: bool = False,
):
    """User holding several OrgRoles: (role, org_wide) pairs share one user.

    staff=True sets Django's is_staff (the admin-site door); OrgRole rows
    still scope what the staffer sees inside."""
    if username:
        user = UserFactory(username=username, is_staff=staff)
    else:
        user = UserFactory(is_staff=staff)
    for role, org_wide in roles:
        OrgRoleFactory(
            organization=venue.organization,
            venue=None if org_wide else venue,
            user=user,
            role=role,
        )
    return user


def user_with_role(
    venue: Venue,
    role: OrgRole.Role,
    username: str | None = None,
    org_wide: bool = False,
    staff: bool = False,
):
    """User holding an OrgRole: avoids the create-user-then-role repetition.

    Pass org_wide=True for org-level roles (venue=None)."""
    return user_with_roles(venue, [(role, org_wide)], username=username, staff=staff)


def with_monthly_plan(user, venue):
    """Attach a valid monthly (unlimited, recurring) plan to a user."""
    plan = PlanFactory(organization=venue.organization, monthly=True)
    return PlanMembershipFactory(user=user, plan=plan, credits_remaining=None)


def make_venue(slug="downtown"):
    """One venue in its own org. The shared _venue replacement: venue slugs
    only need uniqueness per test, orgs are always fresh."""
    return VenueFactory(slug=slug, name=slug.title())


def make_member(username=None, venue=None, credits=10):
    """Org-wide member with a credit pack. Composes user_with_role +
    with_credit_pack; the shared _member replacement."""
    user = user_with_role(venue, OrgRole.Role.MEMBER, username, org_wide=True)
    with_credit_pack(user, venue, credits)
    return user


def make_session(
    venue,
    *,
    title="Spin",
    category=ClassCategory.GROUP,
    price=1,
    capacity=None,
    teacher=None,
    starts_at=None,
):
    """One session tomorrow. Pass starts_at explicitly when the test's
    subject is timing; every other kwarg is the assertion subject.
    Capacity defaults to the model's (15): only pin it when the test is
    about fullness."""
    offering_kwargs = {
        "venue": venue,
        "title": title,
        "category": category,
        "credit_cost": price,
    }
    if teacher is not None:
        offering_kwargs["teacher"] = teacher
    offering = ClassOfferingFactory(**offering_kwargs)
    session_kwargs = {
        "offering": offering,
        "starts_at": starts_at or (timezone.now() + timedelta(days=1)),
    }
    if capacity is not None:
        session_kwargs["capacity"] = capacity
    return ClassSessionFactory(**session_kwargs)


def book(member, session, price=2):
    """Book through the service at a given price. The shared _book
    replacement: stamps price credits, so price is the default."""
    from booking.services import book_session

    session.offering.credit_cost = price
    session.offering.save(update_fields=["credit_cost"])
    return book_session(session=session, member=member)


def make_policy(org, enforcement, late_cancel_hours=12, **scopes):
    """One validated policy. full_clean runs so ambiguous scope sets fail
    at setup, not at resolve time."""
    policy = CancellationPolicyFactory(
        organization=org,
        enforcement=enforcement,
        late_cancel_hours=late_cancel_hours,
        **scopes,
    )
    policy.full_clean()
    policy.save()
    return policy


def api_client(user, venue_slug="downtown"):
    """Authenticated API client pinned to a venue slug."""
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user)
    if venue_slug is not None:
        client.defaults["HTTP_X_VENUE_SLUG"] = venue_slug
    return client


def with_credit_pack(user, venue, credits=10):
    """Attach a credit-pack plan with `credits` remaining to a user."""
    plan = PlanFactory(organization=venue.organization)
    return PlanMembershipFactory(user=user, plan=plan, credits_remaining=credits)
