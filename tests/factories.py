from datetime import timedelta

import factory
from django.contrib.auth import get_user_model
from django.template.defaultfilters import slugify
from django.utils import timezone
from faker import Faker

from aggregators.models import Aggregator
from aggregators.tokens import new_token
from booking.models import CancellationPolicy
from organizations.models import Membership, Organization, OrgRole, Venue
from passes.models import (
    CreditLedger,
    MembershipPlan,
    PlanType,
)
from passes.models import (
    Membership as PlanMembership,
)
from scheduling.catalogue import ClassCategory, ClassOffering, ClassSession
from scheduling.models import ClassType, Room, ScheduledClass

fake = Faker()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        # evaluated at import; fine under test setup
        model = get_user_model()

    username = factory.Sequence(lambda n: f"user-{n}")


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"{fake.company()} {n}")
    slug = factory.LazyAttribute(lambda org: slugify(org.name))
    membership_scope = Organization.Scope.SPANNING

    class Params:
        per_venue = factory.Trait(
            membership_scope=Organization.Scope.PER_VENUE,
        )


class VenueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Venue

    organization = factory.SubFactory(OrganizationFactory)
    slug = factory.Sequence(lambda n: f"venue-{n}")
    name = factory.Sequence(lambda n: f"Venue {n}")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        # No django_get_or_create — duplicate-row tests need real creates.
        model = Membership

    organization = factory.SubFactory(OrganizationFactory)
    # spanning default; per-venue callers pass venue explicitly
    venue = None
    user = factory.SubFactory(UserFactory)
    role = Membership.Role.MEMBER
    policy = None


class OrgRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrgRole

    organization = factory.SubFactory(OrganizationFactory)
    # org-wide default; venue-pinned callers pass venue explicitly
    venue = None
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
    duration_minutes = 60
    credit_cost = 1

    @factory.post_generation
    def teacher_role(offering, create, _extracted, **kwargs):
        """The named teacher holds the teacher role at the venue."""
        if not create:
            return
        OrgRole.objects.get_or_create(
            organization=offering.venue.organization,
            venue=offering.venue,
            user=offering.teacher,
            role=OrgRole.Role.TEACHER,
        )


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


class MembershipPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MembershipPlan

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Plan {n}")
    plan_type = PlanType.CREDIT_PACK
    validity_days = 30


class PlanMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlanMembership

    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(MembershipPlanFactory)
    credits_remaining = 0
    starts_on = factory.LazyFunction(lambda: timezone.now().date())
    ends_on = factory.LazyAttribute(
        lambda membership: (
            membership.starts_on + timedelta(days=membership.plan.validity_days)
        )
    )
    payment_ref = ""


class CreditLedgerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CreditLedger

    membership = factory.SubFactory(PlanMembershipFactory)
    delta = 1
    reason = CreditLedger.Reason.PURCHASE


class ClassTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClassType

    venue = factory.SubFactory(VenueFactory)
    name = factory.Sequence(lambda n: f"Class {n}")
    duration_min = 45


class RoomFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Room

    venue = factory.SubFactory(VenueFactory)
    name = factory.Sequence(lambda n: f"Room {n}")
    capacity = 20


class ScheduledClassFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScheduledClass

    venue = factory.SubFactory(VenueFactory)
    class_type = factory.SubFactory(ClassTypeFactory)
    room = factory.SubFactory(RoomFactory)
    teacher = factory.SubFactory(UserFactory)
    starts_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=1))
    ends_at = factory.LazyAttribute(
        lambda session: (
            session.starts_at + timedelta(minutes=session.class_type.duration_min)
        )
    )


class AggregatorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Aggregator

    slug = factory.Sequence(lambda n: f"aggregator-{n}")
    name = factory.LazyAttribute(lambda partner: partner.slug.title())
    api_token_hash = factory.LazyAttribute(lambda _partner: new_token()[1])
    seat_allotment = 4
    service_user = factory.SubFactory(UserFactory)


def user_with_role(venue, role, username=None, org_wide=False):
    """User holding an OrgRole: avoids the create-user-then-role repetition.

    Pass org_wide=True for org-level roles (venue=None)."""
    user = UserFactory(username=username) if username else UserFactory()
    OrgRoleFactory(
        organization=venue.organization,
        venue=None if org_wide else venue,
        user=user,
        role=role,
    )
    return user
