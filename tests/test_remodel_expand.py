from datetime import timedelta

import pytest

# Expand-phase home for new-model factory smoke tests (ticket bookr-0sr.1).
# Deliberately NOT colocated by domain yet: sibling files still exercise the
# old models that contract will delete, and behavior tickets (.2-.4) rewrite
# those files anyway. At contract (.7), each test either moves to its domain
# file or is deleted as superseded by behavior tests. Do not add to this
# file after .1 closes.
from django.contrib.auth import get_user_model

from booking.models import CancellationPolicy
from organizations.models import Organization, OrgRole
from passes.models import CreditLedger, PlanType
from scheduling.catalogue import ClassCategory
from tests.factories import (  # noqa: WPS235 — expand coverage needs one factory per new model
    CancellationPolicyFactory,
    ClassOfferingFactory,
    ClassSessionFactory,
    CreditLedgerFactory,
    OrganizationFactory,
    OrgRoleFactory,
    PlanFactory,
    PlanMembershipFactory,
    VenueFactory,
)

pytestmark = pytest.mark.django_db


class TestExpandOrgRole:
    def test_factory_builds_org_wide_role(self):
        role = OrgRoleFactory(role=OrgRole.Role.FRONTDESK)

        assert role.pk is not None
        assert role.role == OrgRole.Role.FRONTDESK
        assert role.venue_id is None
        assert role.organization_id is not None
        assert role.user_id is not None

    def test_factory_builds_venue_pinned_role(self):
        from tests.factories import VenueFactory

        venue = VenueFactory()
        role = OrgRoleFactory(
            organization=venue.organization,
            venue=venue,
            role=OrgRole.Role.TEACHER,
        )

        assert role.venue_id == venue.pk
        assert role.organization_id == venue.organization_id


class TestExpandCatalogue:
    def test_offering_factory_builds_priced_workshop(self):
        offering = ClassOfferingFactory(category=ClassCategory.WORKSHOP, credit_cost=2)

        assert offering.pk is not None
        assert offering.category == ClassCategory.WORKSHOP
        assert offering.credit_cost == 2

    def test_offering_factory_links_venue_teacher_and_duration(self):
        offering = ClassOfferingFactory()

        assert offering.duration_minutes == 60
        assert offering.teacher_id is not None
        assert offering.venue_id is not None
        assert OrgRole.objects.filter(
            organization=offering.venue.organization,
            venue=offering.venue,
            user=offering.teacher,
            role=OrgRole.Role.TEACHER,
        ).exists()

    def test_session_derives_end_from_offering(self):
        session = ClassSessionFactory()

        assert session.pk is not None
        assert session.cancelled_at is None
        assert session.ends_at == session.starts_at + timedelta(
            minutes=session.offering.duration_minutes
        )


class TestExpandCancellationPolicy:
    def test_factory_builds_org_wide_rule(self):
        policy = CancellationPolicyFactory()

        assert policy.pk is not None
        assert policy.venue_id is None
        assert policy.class_category is None
        assert policy.plan_type is None

    def test_org_wide_rule_has_zero_specificity(self):
        policy = CancellationPolicyFactory()

        assert policy.specificity == 0
        assert policy.enforcement == CancellationPolicy.Enforcement.NONE

    def test_specificity_counts_narrowed_scopes(self):
        policy = CancellationPolicyFactory(
            venue=ClassOfferingFactory().venue,
            class_category=ClassCategory.WORKSHOP,
        )

        assert policy.specificity == 2

    def test_overlaps_detects_same_scope(self):
        venue = ClassOfferingFactory().venue
        first = CancellationPolicyFactory.build(venue=venue)
        second = CancellationPolicyFactory.build(venue=venue)

        assert first.overlaps(second)

    def test_overlaps_rejects_different_venue(self):
        first = CancellationPolicyFactory.build(venue=ClassOfferingFactory().venue)
        second = CancellationPolicyFactory.build(venue=ClassOfferingFactory().venue)

        assert not first.overlaps(second)


class TestExpandPlans:
    def test_plan_factory_builds_dated_pack(self):
        plan = PlanFactory(plan_type=PlanType.CREDIT_PACK, validity_days=30)

        assert plan.pk is not None
        assert plan.plan_type == PlanType.CREDIT_PACK
        assert plan.validity_days == 30
        assert plan.organization_id is not None

    def test_plan_membership_factory_builds_buyer(self):
        membership = PlanMembershipFactory(credits_remaining=10)

        assert membership.pk is not None
        assert membership.credits_remaining == 10
        assert membership.user_id is not None
        assert membership.plan_id is not None
        assert membership.starts_on is not None

    def test_ledger_row_links_plan_membership(self):
        membership = PlanMembershipFactory()
        row = CreditLedgerFactory(
            membership=membership,
            delta=10,
            reason=CreditLedger.Reason.PURCHASE,
        )

        assert row.pk is not None
        assert membership.ledger_entries.count() == 1


class TestRemodelSeeds:
    def _demo_org(self):
        org = OrganizationFactory(slug="downtown-dance", name="Downtown Dance")
        VenueFactory(organization=org, slug="main", name="Main Studio")
        uptown = OrganizationFactory(
            slug="uptown-box",
            name="Uptown Box",
            membership_scope=Organization.Scope.PER_VENUE,
        )
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
        from booking.models import Booking

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
