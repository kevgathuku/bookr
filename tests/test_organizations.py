import pytest
from django.db import IntegrityError

from organizations.models import Organization

pytestmark = pytest.mark.django_db


#  Organization
#  - Duplicate slug rejected (global uniqueness — the tenant identifier).
#  - Default membership_scope is SPANNING.
#  - __str__ returns the name (admin readability — cheap, keeps the admin honest).

#  Venue
#  - Duplicate slug within one org rejected; same slug in a different org accepted (the per-org constraint from your earlier question).
#  - current_policy returns the open row; raises DoesNotExist when no open row exists (documents the "creation must insert the first version" rule).
#  - __str__ includes org (disambiguates same-named venues in admin dropdowns).

#  VenuePolicy
#  - Two open rows for one venue rejected (one_active_policy_per_venue); a retired row + an open row accepted.
#  - Retire/activate flow: stamp valid_until on v1, insert v2 → current_policy returns v2, v1 preserved untouched.
#  - valid_from auto-populates; valid_until defaults to null.

#  Membership
#  - Same user + org + venue twice rejected; same user in two venues accepted (the two-membership teacher).
#  - Spanning row (venue=None) + pinned row for the same user accepted (different scopes, different rows) — and note the known gap: two spanning rows slip past the
#    NULL-unequal index, so add the service-level guard test when the creation service exists (lesson 4's suite).


class TestOrganizations:
    def test_create_organization(self):
        org = Organization.objects.create(slug="downtown-dance", name="Downtown Dance")

        assert org.pk is not None
        assert org.membership_scope == Organization.Scope.SPANNING
        assert str(org) == org.name

    def test_slug_is_globally_unique(self):
        Organization.objects.create(slug="downtown-dance", name="Downtown Dance")

        with pytest.raises(IntegrityError):
            Organization.objects.create(slug="downtown-dance", name="Downtown Dance 2")
