"""Seed smoke tests: the demo graph builds and re-runs cleanly."""

import pytest
from django.contrib.auth import get_user_model

from booking.models import Booking, CancellationPolicy
from organizations.models import Organization
from tests.factories import OrganizationFactory, VenueFactory

pytestmark = pytest.mark.django_db


class TestRemodelSeeds:
    def _demo_org(self):
        org = OrganizationFactory(slug="downtown-dance", name="Downtown Dance")
        VenueFactory(organization=org, slug="main", name="Main Studio")
        uptown = OrganizationFactory(slug="uptown-box", name="Uptown Box")
        VenueFactory(organization=uptown, slug="box", name="The Box")
        return org

    def test_remodel_graph_builds_new_graph(self):
        from organizations.management.commands.seed_demo import _remodel_graph

        self._demo_org()
        _remodel_graph()

        org = Organization.objects.get(slug="downtown-dance")
        assert CancellationPolicy.objects.filter(
            organization=org, venue__isnull=True
        ).exists()
        assert org.plans.count() >= 1

        member = get_user_model().objects.get(username="demo-member")
        membership = member.plan_memberships.get()
        assert membership.credits_remaining == 9  # booked the demo session
        kinds = set(membership.ledger_entries.values_list("reason", flat=True))
        assert kinds == {"purchase", "booking"}
        assert Booking.objects.filter(member=member).count() == 1

    def test_remodel_graph_is_rerunnable(self):
        from organizations.management.commands.seed_demo import _remodel_graph

        self._demo_org()
        _remodel_graph()
        before = CancellationPolicy.objects.count()
        _remodel_graph()

        assert CancellationPolicy.objects.count() == before
