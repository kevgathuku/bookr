import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
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
from tests.factories import CreditLedgerFactory, UserFactory

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
    return UserFactory(username=username)


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
    from passes.models import Entitlement, Plan, Validity

    return Plan.objects.get_or_create(
        organization=venue.organization,
        name=name,
        defaults={
            "plan_type": "credit_pack",
            "entitlement": Entitlement.CREDITS,
            "credits_included": 10,
            "validity": Validity.FIXED_DURATION,
            "duration_days": 30,
        },
    )[0]


def _member_plan(venue, username, credits=10, plan=None):
    from tests.factories import PlanMembershipFactory

    member = _user(username)
    plan = plan or _plan(venue)
    membership = PlanMembershipFactory(
        user=member, plan=plan, credits_remaining=credits
    )
    return member, membership


class TestLedgerModel:
    def test_str(self):
        _, membership = _member_plan(_venue("ledger-str"), "str", credits=10)
        entry = CreditLedgerFactory(membership=membership, delta=5)

        assert str(entry) == "str → Pack (credit_pack) (10 left): +5 (purchase)"

    def test_delete_refused(self):
        _, membership = _member_plan(_venue("ledger-del"), "del")
        entry = CreditLedgerFactory(membership=membership, delta=5)

        with pytest.raises(ValidationError):
            entry.delete()

    def test_resave_refused(self):
        _, membership = _member_plan(_venue("ledger-resave"), "resave")
        entry = CreditLedgerFactory(membership=membership, delta=5)

        with pytest.raises(ValidationError):
            entry.note = "edited"
            entry.save()

    def test_update_fields_save_refused(self):
        _, membership = _member_plan(_venue("ledger-fields"), "fields")
        entry = CreditLedgerFactory(membership=membership, delta=5)

        with pytest.raises(ValidationError):
            entry.save(update_fields=["note"])

    def test_zero_delta_rejected(self):
        _, membership = _member_plan(_venue("ledger-zero"), "zero")

        with pytest.raises(IntegrityError):
            CreditLedgerFactory(membership=membership, delta=0)

    def test_second_waiver_for_record_rejected(self):
        from booking.models import Booking, CancellationRecord
        from tests.factories import (
            ClassSessionFactory,
            PlanFactory,
            PlanMembershipFactory,
        )

        session = ClassSessionFactory()
        org = session.offering.venue.organization
        member = UserFactory(username="waive")
        plan = PlanFactory(organization=org)
        membership = PlanMembershipFactory(user=member, plan=plan, credits_remaining=10)
        booking = Booking.objects.create(
            session=session, member=member, membership=membership, credits_spent=2
        )
        record = CancellationRecord.objects.create(
            booking=booking,
            member=member,
            organization=org,
            cause="member_cancel",
            was_late=True,
            enforcement_applied="lose_credit",
            snapshot={},
        )
        CreditLedgerFactory(membership=membership, cancellation_record=record, delta=2)

        with pytest.raises(IntegrityError):
            CreditLedgerFactory(
                membership=membership, cancellation_record=record, delta=2
            )

    def test_plan_str(self):
        _, membership = _member_plan(_venue("plan-str"), "plan")

        assert str(membership.plan) == "Pack (credit_pack)"

    def test_membership_str(self):
        _, membership = _member_plan(_venue("member-str"), "mem", credits=10)

        assert str(membership) == "mem → Pack (credit_pack) (10 left)"

    def test_membership_clean_rejects_inverted_dates(self):
        from datetime import date

        _, membership = _member_plan(_venue("member-dates"), "dates")
        membership.starts_on = date(2026, 2, 1)
        membership.valid_until = date(2026, 1, 1)

        with pytest.raises(ValidationError):
            membership.clean()

    def test_membership_clean_accepts_ordered_dates(self):
        _, membership = _member_plan(_venue("member-ok"), "ok")

        membership.clean()


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


class TestPlanAxes:
    """Entitlement x Validity (bookr-4ig/c61): axis-internal states that
    must never persist, plus the NULL-balance/NULL-date acceptances."""

    def _plan(self, venue, **overrides):
        from passes.models import Plan

        base = {
            "organization": venue.organization,
            "name": "Pack",
            "plan_type": "credit_pack",
            "entitlement": "credits",
            "credits_included": 10,
            "validity": "fixed_duration",
            "duration_days": 30,
        }
        base.update(overrides)
        return Plan.objects.create(**base)

    def test_unlimited_with_count_rejected(self):
        with pytest.raises(IntegrityError):
            self._plan(_venue("ax-unl"), entitlement="unlimited", credits_included=10)

    def test_credits_without_count_rejected(self):
        with pytest.raises(IntegrityError):
            self._plan(_venue("ax-cred"), credits_included=None)

    def test_open_ended_with_duration_rejected(self):
        with pytest.raises(IntegrityError):
            self._plan(
                _venue("ax-open"),
                entitlement="unlimited",
                credits_included=None,
                validity="open_ended",
                duration_days=30,
            )

    def test_fixed_without_duration_rejected(self):
        with pytest.raises(IntegrityError):
            self._plan(_venue("ax-fix"), duration_days=None)

    def test_recurring_without_duration_rejected(self):
        with pytest.raises(IntegrityError):
            self._plan(
                _venue("ax-rec"),
                entitlement="unlimited",
                credits_included=None,
                validity="recurring",
                duration_days=None,
            )

    def test_staff_and_aggregator_types_accepted(self):
        venue = _venue("ax-types")
        self._plan(
            venue,
            name="Staff",
            plan_type="staff",
            entitlement="unlimited",
            credits_included=None,
            validity="recurring",
            duration_days=30,
        )
        self._plan(
            venue,
            name="Vehicle",
            plan_type="aggregator",
            entitlement="unlimited",
            credits_included=None,
            validity="fixed_duration",
            duration_days=365,
        )

    def test_unlimited_membership_holds_null_balance(self):
        from datetime import timedelta

        from django.utils import timezone

        venue = _venue("ax-null")
        plan = self._plan(
            venue,
            entitlement="unlimited",
            credits_included=None,
            validity="recurring",
            duration_days=30,
        )
        membership = PlanMembership.objects.create(
            user=_user("null-bal"),
            plan=plan,
            credits_remaining=None,
            starts_on=timezone.now().date(),
            valid_until=timezone.now().date() + timedelta(days=30),
        )
        assert membership.credits_remaining is None

    def test_open_ended_membership_holds_null_date(self):
        from django.utils import timezone

        venue = _venue("ax-nodate")
        plan = self._plan(
            venue,
            entitlement="unlimited",
            credits_included=None,
            validity="open_ended",
            duration_days=None,
        )
        membership = PlanMembership.objects.create(
            user=_user("nodate"),
            plan=plan,
            credits_remaining=None,
            starts_on=timezone.now().date(),
            valid_until=None,
        )
        assert membership.valid_until is None

    def test_inverted_dates_rejected(self):
        from datetime import timedelta

        from django.utils import timezone

        venue = _venue("ax-inv")
        plan = self._plan(venue)
        with pytest.raises(IntegrityError):
            PlanMembership.objects.create(
                user=_user("inv"),
                plan=plan,
                credits_remaining=5,
                starts_on=timezone.now().date(),
                valid_until=timezone.now().date() - timedelta(days=1),
            )


class TestPostEntry:
    """post_entry: the single choke-point for every credit movement."""

    def test_posts_row_and_bumps_cache(self):
        from passes.services import post_entry

        _, membership = _member_plan(_venue("pe-ok"), "ok", credits=10)
        row = post_entry(
            membership,
            -3,
            CreditLedger.Reason.BOOKING,
            booking=None,
        )

        assert row.delta == -3
        membership.refresh_from_db()
        assert membership.credits_remaining == 7
        assert membership.ledger_entries.count() == 1

    def test_zero_delta_refused(self):
        from django.core.exceptions import ValidationError

        from passes.services import post_entry

        _, membership = _member_plan(_venue("pe-zero"), "zero", credits=10)

        with pytest.raises(ValidationError):
            post_entry(membership, 0, CreditLedger.Reason.BOOKING, booking=None)

    def test_floor_breach_raises_insufficient(self):
        from booking.errors import CreditInsufficient
        from passes.services import post_entry

        _, membership = _member_plan(_venue("pe-floor"), "floor", credits=2)

        with pytest.raises(CreditInsufficient):
            post_entry(membership, -3, CreditLedger.Reason.BOOKING, booking=None)
        membership.refresh_from_db()
        assert membership.credits_remaining == 2
        assert membership.ledger_entries.count() == 0

    def test_unlimited_takes_no_rows(self):
        from django.core.exceptions import ValidationError

        from passes.models import Entitlement, Validity
        from passes.services import post_entry

        venue = _venue("pe-unl")
        from passes.models import Plan

        plan = Plan.objects.create(
            organization=venue.organization,
            name="Monthly",
            plan_type="monthly",
            entitlement=Entitlement.UNLIMITED,
            validity=Validity.RECURRING,
            duration_days=30,
        )
        membership = PlanMembership.objects.create(
            user=_user("unlimited"),
            plan=plan,
            credits_remaining=None,
            starts_on=plan_starts_today(),
            valid_until=None,
        )

        with pytest.raises(ValidationError):
            post_entry(membership, -1, CreditLedger.Reason.BOOKING, booking=None)
        assert membership.ledger_entries.count() == 0

    def test_duplicate_spend_for_one_booking_rejected(self):
        from django.db import IntegrityError

        from passes.services import post_entry

        _, membership = _member_plan(_venue("pe-dupe"), "dupe", credits=10)
        booking = _booking_for(membership)

        post_entry(membership, -1, CreditLedger.Reason.BOOKING, booking=booking)
        with pytest.raises(IntegrityError):
            post_entry(membership, -1, CreditLedger.Reason.BOOKING, booking=booking)


def plan_starts_today():
    from django.utils import timezone

    return timezone.now().date()


def _booking_for(membership):
    from tests.factories import ClassOfferingFactory, ClassSessionFactory, VenueFactory

    venue = VenueFactory(organization=membership.plan.organization)
    offering = ClassOfferingFactory(venue=venue)
    session = ClassSessionFactory(offering=offering)
    from booking.models import Booking

    return Booking.objects.create(
        session=session,
        member=membership.user,
        membership=membership,
        credits_spent=1,
    )


class TestReconcileLedger:
    def test_agrees_on_clean_data(self):
        from django.core.management import call_command

        from passes.services import post_entry

        _, membership = _member_plan(_venue("rec-ok"), "ok", credits=0)
        post_entry(membership, 10, CreditLedger.Reason.PURCHASE)

        call_command("reconcile_ledger")

    def test_fails_on_drift(self):
        from django.core.management import CommandError, call_command

        _, membership = _member_plan(_venue("rec-drift"), "drift", credits=10)
        PlanMembership.objects.filter(pk=membership.pk).update(credits_remaining=99)

        with pytest.raises(CommandError):
            call_command("reconcile_ledger")


class TestGrantGoodwill:
    """grant_goodwill: one atomic mint of plan + membership + PURCHASE."""

    def test_mints_all_three_rows(self):
        from datetime import timedelta

        from passes.models import PlanType
        from passes.services import grant_goodwill

        venue = _venue("grant-ok")
        member = _user("granted")
        membership, created = grant_goodwill(
            organization=venue.organization,
            user=member,
            credits=2,
            duration_days=30,
            note="late cancel comp",
            created_by=member,
            incident_key="incident-1",
        )

        assert created is True
        assert membership.credits_remaining == 2
        assert membership.payment_ref == "incident-1"
        assert membership.plan.plan_type == PlanType.COMPLIMENTARY
        assert membership.plan.credits_included == 2
        assert membership.valid_until == membership.starts_on + timedelta(days=30)
        purchase = membership.ledger_entries.get(
            reason=CreditLedger.Reason.PURCHASE,
        )
        assert purchase.delta == 2

    def test_same_incident_key_returns_existing(self):
        from passes.services import grant_goodwill

        venue = _venue("grant-idem")
        member = _user("idem")
        first, _ = grant_goodwill(
            organization=venue.organization,
            user=member,
            credits=2,
            note="comp",
            created_by=member,
            incident_key="incident-9",
        )
        second, created = grant_goodwill(
            organization=venue.organization,
            user=member,
            credits=2,
            note="comp",
            created_by=member,
            incident_key="incident-9",
        )

        assert created is False
        assert second.pk == first.pk
        assert (
            CreditLedger.objects.filter(
                membership=first, reason=CreditLedger.Reason.PURCHASE
            ).count()
            == 1
        )

    def test_duplicate_payment_ref_rejected_at_db(self):
        from django.db import IntegrityError

        from tests.factories import PlanMembershipFactory

        venue = _venue("grant-dupe")
        member = _user("dupe")
        PlanMembershipFactory(
            user=member,
            plan=_plan(venue),
            credits_remaining=0,
            payment_ref="incident-x",
        )

        with pytest.raises(IntegrityError):
            PlanMembershipFactory(
                user=member,
                plan=_plan(venue),
                credits_remaining=0,
                payment_ref="incident-x",
            )
