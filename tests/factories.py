import factory
from django.template.defaultfilters import slugify
from faker import Faker

from organizations.models import Organization, Venue

fake = Faker()


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
