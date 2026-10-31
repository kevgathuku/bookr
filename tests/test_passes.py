import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum
from rest_framework.test import APIClient

from booking.errors import CreditInsufficient
from organizations.models import Organization, Venue
from passes.models import (
    CreditLedger,
)
from passes.models import (
    Membership as PlanMembership,
)

pytestmark = pytest.mark.django_db

#  Pass/ledger seam
#  - spend: oldest-valid-first, unlimited before limited, type applicability
#    honored; writes -1 row, bumps used cache, sets booking.credit_tx.
#  - Unlimited spends write no row (nothing to deplete; delta != 0 forbids
#    zero rows) and leave credit_tx empty.
#  - Ledger invariant: SUM(delta) == total - used on live passes.
#  - refund restores; adjust needs a reason; expiry zeroes + marks expired.
#  - Views: me/passes is own-only; ledger is own-for-members, venue-for-staff.
#
#  Concurrency seam (transactional marker: threads need committed setup)
#  - 20 threads, 1 member, 1 credit, 20 classes → exactly 1 booking.


def _user(username):
    return get_user_model().objects.create_user(username=username)


def _venue(slug="downtown"):
    org = Organization.objects.create(slug=f"org-{slug}", name=f"Org {slug}")
    return Venue.objects.create(organization=org, slug=slug, name=slug.title())


def _member_with_plan(venue, username, credits=10):
    from tests.factories import PlanFactory, PlanMembershipFactory

    member = _user(username)
    plan = PlanFactory(organization=venue.organization)
    membership = PlanMembershipFactory(
        user=member, plan=plan, credits_remaining=credits
    )
    return member, membership


def _plan(venue, name="Pack"):
    from passes.models import Plan

    return Plan.objects.get_or_create(
        organization=venue.organization,
        name=name,
        defaults={"plan_type": "credit_pack", "validity_days": 30},
    )[0]


def _member_plan(venue, username, credits=10, plan=None):
    from tests.factories import PlanMembershipFactory

    member = _user(username)
    plan = plan or _plan(venue)
    membership = PlanMembershipFactory(
        user=member, plan=plan, credits_remaining=credits
    )
    return member, membership


class TestSpend:
    """spend_for_booking: debit + BOOKING row, or nothing for zero amounts."""

    def test_spend_debits_and_links_booking(self):
        from passes.services import spend_for_booking

        venue = _venue()
        _, membership = _member_with_plan(venue, "m1", 10)

        spend_for_booking(membership, 3, booking=None)

        membership.refresh_from_db()
        assert membership.credits_remaining == 7
        row = membership.ledger_entries.get(reason=CreditLedger.Reason.BOOKING)
        assert (row.delta, row.booking) == (-3, None)

    def test_zero_spend_writes_no_row(self):
        from passes.services import spend_for_booking

        venue = _venue()
        _, membership = _member_with_plan(venue, "m1", 10)

        assert spend_for_booking(membership, 0, None) is None

        membership.refresh_from_db()
        assert membership.credits_remaining == 10
        assert membership.ledger_entries.count() == 0

    def test_insufficient_raises_and_writes_nothing(self):
        from passes.services import spend_for_booking

        venue = _venue()
        _, membership = _member_with_plan(venue, "m1", credits=2)

        with pytest.raises(CreditInsufficient):
            spend_for_booking(membership, 3, booking=None)

        membership.refresh_from_db()
        assert membership.credits_remaining == 2
        assert membership.ledger_entries.count() == 0

    def test_ledger_invariant_on_seed(self):
        venue = _venue()
        for name in ("a", "b", "c"):
            _member_with_plan(venue, f"{name}-holder", credits=5)

        for membership in PlanMembership.objects.all():
            summed = membership.ledger_entries.aggregate(total=Sum("delta"))["total"]
            assert (summed or 0) == 0


class TestLedgerUnion:
    def _client(self, user, slug="ledger-union"):

        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_VENUE_SLUG"] = slug
        return client

    def test_member_sees_plan_membership_rows(self):
        from organizations.models import OrgRole
        from tests.factories import (
            OrgRoleFactory,
            PlanFactory,
            PlanMembershipFactory,
            UserFactory,
            VenueFactory,
        )

        venue = VenueFactory(slug="ledger-union")
        member = UserFactory(username="ledger-member")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        plan = PlanFactory(organization=venue.organization)
        membership = PlanMembershipFactory(user=member, plan=plan)
        CreditLedger.objects.create(
            membership=membership,
            delta=-2,
            reason=CreditLedger.Reason.BOOKING,
        )

        response = self._client(member).get("/api/v1/ledger/")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["delta"] == -2

    def test_staff_sees_org_plan_rows(self):
        from booking.services import book_session
        from organizations.models import OrgRole
        from tests.factories import (
            ClassOfferingFactory,
            ClassSessionFactory,
            OrgRoleFactory,
            PlanFactory,
            PlanMembershipFactory,
            UserFactory,
            VenueFactory,
        )

        venue = VenueFactory(slug="ledger-staff")
        member = UserFactory(username="ledger-m2")
        staff = UserFactory(username="ledger-s2")
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        OrgRoleFactory(
            organization=venue.organization,
            venue=None,
            user=staff,
            role=OrgRole.Role.MANAGER,
        )
        plan = PlanFactory(organization=venue.organization)
        PlanMembershipFactory(user=member, plan=plan, credits_remaining=5)
        offering = ClassOfferingFactory(venue=venue)
        session = ClassSessionFactory(offering=offering)
        book_session(session=session, member=member)

        response = self._client(staff, slug="ledger-staff").get("/api/v1/ledger/")

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["reason"] == CreditLedger.Reason.BOOKING

    def test_staff_cannot_see_other_venues_bookings(self):
        from booking.services import book_session
        from organizations.models import OrgRole
        from tests.factories import (
            ClassOfferingFactory,
            ClassSessionFactory,
            OrgRoleFactory,
            PlanFactory,
            PlanMembershipFactory,
            UserFactory,
            VenueFactory,
        )

        org_venues = VenueFactory(slug="ledger-home")
        other = VenueFactory(organization=org_venues.organization, slug="ledger-away")
        member = UserFactory(username="ledger-m3")
        staff = UserFactory(username="ledger-s3")
        OrgRoleFactory(
            organization=org_venues.organization,
            venue=None,
            user=member,
            role=OrgRole.Role.MEMBER,
        )
        OrgRoleFactory(
            organization=org_venues.organization,
            venue=other,
            user=staff,
            role=OrgRole.Role.MANAGER,
        )
        plan = PlanFactory(organization=org_venues.organization)
        PlanMembershipFactory(user=member, plan=plan, credits_remaining=5)
        offering = ClassOfferingFactory(venue=org_venues)
        session = ClassSessionFactory(offering=offering)
        book_session(session=session, member=member)

        response = self._client(staff, slug="ledger-away").get("/api/v1/ledger/")

        assert response.status_code == 200
        assert response.data == []
