import pytest
from django.db import IntegrityError

from organizations.models import Organization, Venue
from tests.factories import OrganizationFactory, VenueFactory

pytestmark = pytest.mark.django_db

#  Venue
#  - Duplicate slug within one org rejected; same slug in a different org
#    accepted.
#  - __str__ includes org (disambiguates same-named venues in admin dropdowns).


class TestOrganizations:
    def test_create_organization(self):
        org = OrganizationFactory(slug="downtown-dance", name="Downtown Dance")

        assert org.pk is not None
        assert str(org) == org.name

    def test_slug_is_globally_unique(self):
        OrganizationFactory(slug="downtown-dance", name="Downtown Dance")

        # Second half stays objects.create: the factory's get_or_create on
        # slug would return the row instead of raising IntegrityError.
        with pytest.raises(IntegrityError):
            Organization.objects.create(slug="downtown-dance", name="Downtown Dance 2")


class TestVenue:
    def test_slug_unique_per_org(self):
        org = OrganizationFactory(slug="o1", name="O1")
        Venue.objects.create(organization=org, slug="downtown", name="Downtown")

        with pytest.raises(IntegrityError):
            Venue.objects.create(organization=org, slug="downtown", name="Downtown 2")

    def test_same_slug_different_org(self):
        o1 = OrganizationFactory(slug="o1", name="O1")
        o2 = OrganizationFactory(slug="o2", name="O2")
        Venue.objects.create(organization=o1, slug="downtown", name="Downtown")

        venue = Venue.objects.create(organization=o2, slug="downtown", name="Downtown")

        assert venue.pk is not None

    def test_str_includes_org(self):
        venue = VenueFactory()

        assert venue.organization.name in str(venue)
