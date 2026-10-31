from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APIClient

from booking.errors import CreditInsufficient
from organizations.models import Membership, Organization, Venue
from passes.models import (
    CreditLedger,
    MemberPass,
    PassProduct,
)
from passes.models import Membership as PlanMembership
from passes.services import adjust_credit, expire_passes, issue_pass

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


def _product(venue, name="Ten Pack", credits=5, types=None):
    product = PassProduct.objects.create(
        venue=venue, name=name, credits_total=credits, validity_days=30
    )
    if types:
        product.applicable_class_types.set(types)
    return product


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


class TestRefundAdjustExpire:
    def test_expire_task_runs_service(self):
        from passes.tasks import expire_passes_task

        venue = _venue()
        member = _user("exp-task")
        member_pass = issue_pass(member, _product(venue))
        member_pass.valid_until = timezone.now() - timedelta(seconds=1)
        member_pass.save()

        expire_passes_task()

        member_pass.refresh_from_db()
        assert member_pass.status == MemberPass.Status.EXPIRED

    def test_adjust_needs_reason(self):
        venue = _venue()
        member_pass = issue_pass(_user("m1"), _product(venue))

        with pytest.raises(ValidationError):
            adjust_credit(member_pass, 1, reason="", staff=_user("boss"))

    def test_expire_zeroes_and_marks(self):
        venue = _venue()
        member = _user("m1")
        member_pass = issue_pass(member, _product(venue))
        member_pass.valid_until = timezone.now() - timedelta(seconds=1)
        member_pass.save()

        expire_passes()

        member_pass.refresh_from_db()
        assert member_pass.status == MemberPass.Status.EXPIRED
        summed = member_pass.entries.aggregate(total=Sum("delta"))["total"]
        assert summed == 0


@pytest.mark.django_db(transaction=True)
class TestLastCreditRace:
    def test_twenty_threads_one_balance_yields_one_spend(self):
        from passes.services import spend_for_booking

        venue = _venue(slug="race")
        _member, membership = _member_with_plan(venue, "racer", credits=10)

        def attempt(amount):
            try:
                spend_for_booking(membership, amount, booking=None)
                return "spent"
            except CreditInsufficient:
                return "empty"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(attempt, [6 for _ in range(20)]))

        membership.refresh_from_db()
        assert membership.credits_remaining >= 0
        assert outcomes.count("spent") == 1
        assert outcomes.count("empty") == 19


class TestPassViews:
    def _client(self, user, slug="downtown"):
        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_VENUE_SLUG"] = slug
        return client

    def test_me_passes_own_only(self):
        venue = _venue()
        mine = _user("mine")
        other = _user("other")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=mine,
            role=Membership.Role.MEMBER,
        )
        issue_pass(mine, _product(venue))
        issue_pass(other, _product(venue, name="other-pack"))

        response = self._client(mine).get("/api/v1/me/passes/")

        assert response.status_code == 200
        assert len(response.data) == 1

    def test_ledger_scope_member_vs_staff(self):
        venue = _venue()
        member = _user("member")
        staff = _user("staff")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=member,
            role=Membership.Role.MEMBER,
        )
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=staff,
            role=Membership.Role.MANAGER,
        )
        member_pass = issue_pass(member, _product(venue))
        CreditLedger.objects.create(
            member_pass=member_pass, delta=-1, reason=CreditLedger.Reason.BOOKING
        )

        own = self._client(member).get("/api/v1/ledger/")
        venue_wide = self._client(staff).get("/api/v1/ledger/")

        assert own.status_code == 200
        assert venue_wide.status_code == 200
        assert len(own.data) == len(venue_wide.data) == 2  # purchase + spend

    def test_adjust_staff_200_member_403_reasonless_400(self):
        venue = _venue()
        member = _user("member")
        staff = _user("staff")
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=member,
            role=Membership.Role.MEMBER,
        )
        Membership.objects.create(
            organization=venue.organization,
            venue=venue,
            user=staff,
            role=Membership.Role.MANAGER,
        )
        member_pass = issue_pass(member, _product(venue))
        payload = {"member_pass": member_pass.pk, "delta": 2, "reason": "goodwill"}

        assert (
            self._client(member).post("/api/v1/ledger/adjust/", payload).status_code
            == 403
        )
        assert (
            self._client(staff).post("/api/v1/ledger/adjust/", payload).status_code
            == 200
        )
        nor_reason = {"member_pass": member_pass.pk, "delta": 2, "reason": ""}
        assert (
            self._client(staff).post("/api/v1/ledger/adjust/", nor_reason).status_code
            == 400
        )


class TestLedgerNote:
    def test_adjust_stores_staff_note(self):
        venue = _venue("note")
        member = _user("noted")
        member_pass = issue_pass(member, _product(venue))

        adjust_credit(member_pass, 1, reason="goodwill", staff=_user("boss"))

        row = member_pass.entries.get(reason="adjustment")
        assert row.note == "goodwill"


class TestLedgerUnion:
    def _client(self, user, slug="ledger-union"):
        from rest_framework.test import APIClient

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
        from organizations.models import OrgRole
        from tests.factories import (
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
        membership = PlanMembershipFactory(user=member, plan=plan)
        CreditLedger.objects.create(
            membership=membership,
            delta=-2,
            reason=CreditLedger.Reason.BOOKING,
        )

        response = self._client(staff, slug="ledger-staff").get("/api/v1/ledger/")

        assert response.status_code == 200
        assert len(response.data) == 1
