import factory
from django.contrib.auth import get_user_model
from django.template.defaultfilters import slugify
from faker import Faker

from organizations.models import Membership, Organization, Venue

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
