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

        assert org.slug == "downtown-dance"
        assert org.name == "Downtown Dance"
        assert str(org) == "Downtown Dance"

    def test_slug_is_globally_unique(self):
        OrganizationFactory(slug="downtown-dance", name="Downtown Dance")

        # Second half stays objects.create: the factory's get_or_create on
        # slug would return the row instead of raising IntegrityError.
        with pytest.raises(IntegrityError):
            Organization.objects.create(slug="downtown-dance", name="Downtown Dance 2")


class TestVenue:
    def test_slug_unique_per_org(self):
        org = OrganizationFactory(slug="o1", name="O1")
        VenueFactory(organization=org, slug="downtown", name="Downtown")

        with pytest.raises(IntegrityError):
            VenueFactory(organization=org, slug="downtown", name="Downtown 2")

    def test_same_slug_different_org(self):
        o1 = OrganizationFactory(slug="o1", name="O1")
        o2 = OrganizationFactory(slug="o2", name="O2")

        VenueFactory(organization=o1, slug="downtown", name="Downtown")
        venue = VenueFactory(organization=o2, slug="downtown", name="Downtown")

        assert venue.pk is not None
        assert venue.slug == "downtown"

    def test_str_includes_org(self):
        venue = VenueFactory()
        name = venue.name
        org_name = venue.organization.name

        assert str(venue) == f"{name} ({org_name})"

    def test_default_time_zone_is_utc(self):
        assert VenueFactory().time_zone == "UTC"

    def test_delete_organization_cascades_to_venues(self):
        venue = VenueFactory()

        venue.organization.delete()

        assert not Venue.objects.filter(pk=venue.pk).exists()
