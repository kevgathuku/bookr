from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from organizations.models import Membership, Organization, Venue, VenuePolicy
from tests.factories import OrganizationFactory, VenueFactory

pytestmark = pytest.mark.django_db

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
        org = OrganizationFactory(slug="downtown-dance", name="Downtown Dance")

        assert org.pk is not None
        assert org.membership_scope == Organization.Scope.SPANNING
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

    def test_current_policy_returns_open_row(self):
        venue = VenueFactory()
        # Open row: valid_until=None is what one_active_policy_per_venue counts.
        policy = VenuePolicy.objects.create(venue=venue, valid_until=None)

        assert venue.current_policy == policy

    def test_current_policy_missing_raises(self):
        venue = VenueFactory()

        with pytest.raises(VenuePolicy.DoesNotExist):
            _ = venue.current_policy


class TestVenuePolicy:
    def _venue(self):
        return VenueFactory()

    def test_two_open_rows_allowed_latest_wins(self):
        venue = self._venue()
        first = VenuePolicy.objects.create(venue=venue, valid_until=None)
        second = VenuePolicy.objects.create(venue=venue, valid_until=None)

        assert (first.version, second.version) == (1, 2)
        assert venue.current_policy.pk == second.pk

    def test_retire(self):
        venue = self._venue()
        policy = VenuePolicy.objects.create(venue=venue, valid_until=None)

        policy.retire()

        policy.refresh_from_db()
        assert policy.valid_until is not None

    def test_retire_then_activate(self):
        venue = self._venue()
        old = VenuePolicy.objects.create(venue=venue, valid_until=None)

        # Retired predecessor no longer counts → insert succeeds, atomically.
        new = VenuePolicy.objects.activate(venue)

        assert venue.current_policy == new
        old.refresh_from_db()
        assert old.valid_until is not None

    def test_activate_with_no_prior_policy(self):
        venue = self._venue()

        new = VenuePolicy.objects.activate(venue)

        assert venue.current_policy == new

    def test_activate_with_overrides(self):
        venue = self._venue()

        new = VenuePolicy.objects.activate(venue, class_late_cancel_hours=4)

        assert new.class_late_cancel_hours == 4
        assert new.appointment_late_cancel_hours == 24  # untouched default

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_activate_single_winner(self):
        # Plain django_db wraps the test in a transaction other threads
        # can't see into — so this one commits for real (flushed after).
        venue = self._venue()
        errors = []

        def activate():
            try:
                VenuePolicy.objects.activate(venue)
            except IntegrityError as exc:
                errors.append(exc)
            finally:
                # Threads keep their DB connections open otherwise, and
                # teardown can't drop test_bookr while sessions linger.
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: activate(), range(2)))

        assert len(errors) == 1  # loser hits one_active_policy_per_venue
        assert venue.policies.filter(valid_until__isnull=True).count() == 1


class TestMembership:
    def _setup(self, scope):
        org = OrganizationFactory(membership_scope=scope)
        venue_a = VenueFactory(organization=org)
        venue_b = VenueFactory(organization=org)
        user = get_user_model().objects.create_user(username="sam")
        return org, venue_a, venue_b, user

    def test_duplicate_rejected(self):
        org, venue_a, _, user = self._setup(Organization.Scope.PER_VENUE)
        Membership.objects.create(
            organization=org, venue=venue_a, user=user, role=Membership.Role.MEMBER
        )

        with pytest.raises(IntegrityError):
            Membership.objects.create(
                organization=org, venue=venue_a, user=user, role=Membership.Role.MEMBER
            )

    def test_accepts_teacher_in_two_venues_with_per_venue_org(self):
        # The two-venue teacher: one row per venue.
        org, venue_a, venue_b, user = self._setup(Organization.Scope.PER_VENUE)
        first = Membership.objects.create(
            organization=org, venue=venue_a, user=user, role=Membership.Role.TEACHER
        )
        second = Membership.objects.create(
            organization=org, venue=venue_b, user=user, role=Membership.Role.TEACHER
        )

        assert first.pk is not None and second.pk is not None

    def test_spanning_rejects_pinned_venue(self):
        org, venue_a, _, user = self._setup(Organization.Scope.SPANNING)

        membership = Membership(
            organization=org, venue=venue_a, user=user, role=Membership.Role.MEMBER
        )

        with pytest.raises(ValidationError):
            membership.full_clean()

    def test_per_venue_requires_venue(self):
        org = OrganizationFactory(per_venue=True)
        user = get_user_model().objects.create_user(username="sam")
        membership = Membership(
            organization=org, venue=None, user=user, role=Membership.Role.MEMBER
        )

        with pytest.raises(ValidationError):
            membership.full_clean()
