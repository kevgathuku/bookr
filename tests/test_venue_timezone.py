import pytest
from django.core.exceptions import ValidationError

from organizations.models import Organization, Venue

pytestmark = pytest.mark.django_db


def _org():
    return Organization.objects.create(slug="tz-org", name="TZ Org")


class TestVenueTimeZone:
    def test_valid_iana_zone_passes(self):
        venue = Venue(
            organization=_org(), slug="nbo", name="Nairobi", time_zone="Africa/Nairobi"
        )

        venue.full_clean()

    def test_bogus_zone_fails(self):
        venue = Venue(
            organization=_org(),
            slug="nowhere",
            name="Nowhere",
            time_zone="Narnia/Nowhere",
        )

        with pytest.raises(ValidationError):
            venue.full_clean()

    def test_typo_zone_fails(self):
        venue = Venue(
            organization=_org(), slug="typo", name="Typo", time_zone="Afrika/Nairobi"
        )

        with pytest.raises(ValidationError):
            venue.full_clean()
