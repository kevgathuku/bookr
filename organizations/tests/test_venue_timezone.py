import pytest
from django.core.exceptions import ValidationError

from organizations.models import Venue, _iana_time_zone
from tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return OrganizationFactory(slug="tz-org", name="TZ Org")


class TestVenueTimeZone:
    def test_valid_iana_zone_passes(self, org):
        venue = Venue(
            organization=org, slug="nbo", name="Nairobi", time_zone="Africa/Nairobi"
        )

        venue.full_clean()

    def test_bogus_zone_fails(self, org):
        venue = Venue(
            organization=org,
            slug="nowhere",
            name="Nowhere",
            time_zone="Narnia/Nowhere",
        )

        with pytest.raises(ValidationError):
            venue.full_clean()

    def test_typo_zone_fails(self, org):
        venue = Venue(
            organization=org, slug="typo", name="Typo", time_zone="Afrika/Nairobi"
        )

        with pytest.raises(ValidationError):
            venue.full_clean()

    @pytest.mark.parametrize("bad_value", [None, 123])
    def test_non_string_zone_fails(self, bad_value):
        with pytest.raises(ValidationError):
            _iana_time_zone(bad_value)
