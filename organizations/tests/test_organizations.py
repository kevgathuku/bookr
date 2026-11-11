import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from organizations.models import Organization, OrgRole, Venue
from tests.factories import (
    OrganizationFactory,
    OrgRoleFactory,
    UserFactory,
    VenueFactory,
)

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


class TestOrgRole:
    @pytest.mark.parametrize("role", list(OrgRole.Role))
    def test_str_org_wide(self, role):
        org_role = OrgRoleFactory(role=role, venue=None)

        assert str(org_role) == f"{org_role.user} · {role.value} @ all venues"

    @pytest.mark.parametrize("role", list(OrgRole.Role))
    def test_str_single_venue(self, role):
        venue = VenueFactory(name="Downtown")
        org_role = OrgRoleFactory(role=role, venue=venue)

        assert str(org_role) == f"{org_role.user} · {role.value} @ Downtown"

    def test_cross_org_venue_rejected(self):
        org = OrganizationFactory(slug="home")
        other = OrganizationFactory(slug="away")
        venue = VenueFactory(organization=other, slug="away-main")
        # build: save() runs full_clean, so a coherent factory create
        # would raise before the explicit assertion below.
        role = OrgRoleFactory.build(organization=org, venue=venue)

        with pytest.raises(ValidationError):
            role.full_clean()

    def test_same_org_venue_accepted(self):
        org = OrganizationFactory(slug="home")
        venue = VenueFactory(organization=org, slug="home-main")
        role = OrgRoleFactory(organization=org, venue=venue)

        role.full_clean()

    def test_org_wide_role_accepted(self):
        role = OrgRoleFactory(venue=None)

        role.full_clean()

    def test_save_runs_cross_org_check(self):
        org = OrganizationFactory(slug="save-home")
        venue = VenueFactory(
            organization=OrganizationFactory(slug="save-away"),
            slug="save-away-main",
        )

        # Factory saves: the cross-org ValidationError must surface here,
        # not only on an explicit full_clean() call.
        with pytest.raises(ValidationError):
            OrgRoleFactory(organization=org, venue=venue)

    def test_duplicate_org_wide_role_rejected(self):
        existing = OrgRoleFactory(venue=None, role=OrgRole.Role.MEMBER)

        # bulk_create skips save()/full_clean: this proves the DB
        # constraint, not model validation (Postgres NULL != NULL trap).
        with pytest.raises(IntegrityError):
            OrgRole.objects.bulk_create(
                [
                    OrgRole(
                        organization=existing.organization,
                        venue=None,
                        user=existing.user,
                        role=existing.role,
                    )
                ]
            )

    def test_duplicate_venue_pinned_role_rejected(self):
        venue = VenueFactory()
        existing = OrgRoleFactory(venue=venue, role=OrgRole.Role.TEACHER)

        # bulk_create skips save()/full_clean: this proves the DB constraint.
        with pytest.raises(IntegrityError):
            OrgRole.objects.bulk_create(
                [
                    OrgRole(
                        organization=existing.organization,
                        venue=venue,
                        user=existing.user,
                        role=existing.role,
                    )
                ]
            )

    def test_org_wide_and_pinned_same_role_coexist(self):
        venue = VenueFactory()
        user = UserFactory()
        org_wide = OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=user,
            role=OrgRole.Role.MEMBER,
        )
        pinned = OrgRoleFactory(venue=venue, user=user, role=OrgRole.Role.MEMBER)

        assert {org_wide.pk, pinned.pk} == set(
            OrgRole.objects.filter(user=user).values_list("pk", flat=True)
        )

    def test_covering_excludes_other_org_org_wide_rows(self):
        venue = VenueFactory()
        mine = OrgRoleFactory(organization=venue.organization, venue=None)
        other = OrgRoleFactory(venue=None, role=OrgRole.Role.MEMBER)

        covered_ids = set(OrgRole.objects.covering(venue).values_list("pk", flat=True))

        assert mine.pk in covered_ids
        assert other.pk not in covered_ids
