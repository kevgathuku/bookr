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
from booking.services import book_seat
from organizations.models import Membership, Organization, Venue
from passes.models import MemberPass, PassProduct
from passes.services import adjust_credit, expire_passes, issue_pass, refund_credit
from scheduling.models import ClassType, Room, ScheduledClass

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


def _product(venue, name="Ten Pack", credits=5, types=None):
    product = PassProduct.objects.create(
        venue=venue, name=name, credits_total=credits, validity_days=30
    )
    if types:
        product.applicable_class_types.set(types)
    return product


def _class(venue, name="Spin", teacher=None, start=None):
    start = start or (timezone.now() + timedelta(days=1))
    class_type, _ = ClassType.objects.get_or_create(
        venue=venue, name=name, defaults={"duration_min": 45}
    )
    room, _ = Room.objects.get_or_create(
        venue=venue, name=f"Studio-{name}", defaults={"capacity": 20}
    )
    return ScheduledClass.objects.create(
        venue=venue,
        class_type=class_type,
        room=room,
        teacher=teacher or _user(f"teacher-{venue.slug}-{name}"),
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )


def _book(member, klass, key="k"):
    return book_seat(member, klass, idempotency_key=key)


class TestSpend:
    def test_spend_writes_row_and_links_booking(self):
        venue = _venue()
        member = _user("m1")
        member_pass = issue_pass(member, _product(venue))
        booking = _book(member, _class(venue))

        member_pass.refresh_from_db()
        booking.refresh_from_db()
        assert member_pass.credits_used == 1
        assert booking.credit_tx is not None
        assert booking.credit_tx.delta == -1
        assert booking.credit_tx.member_pass == member_pass

    def test_oldest_valid_first(self):
        venue = _venue()
        member = _user("m1")
        old = issue_pass(member, _product(venue, name="old"))
        old.valid_from -= timedelta(days=10)
        old.save()
        new = issue_pass(member, _product(venue, name="new"))

        _book(member, _class(venue))

        old.refresh_from_db()
        new.refresh_from_db()
        assert (old.credits_used, new.credits_used) == (1, 0)

    def test_unlimited_first(self):
        venue = _venue()
        member = _user("m1")
        limited = issue_pass(member, _product(venue, name="limited"))
        unlimited = issue_pass(member, _product(venue, name="unlimited", credits=None))

        booking = _book(member, _class(venue))

        limited.refresh_from_db()
        booking.refresh_from_db()
        assert limited.credits_used == 0
        assert unlimited.credits_used == 0
        assert booking.credit_tx is None  # nothing to track, no row

    def test_type_applicability(self):
        venue = _venue()
        member = _user("m1")
        yoga = ClassType.objects.create(venue=venue, name="Yoga", duration_min=60)
        issue_pass(member, _product(venue, types=[yoga]))

        with pytest.raises(CreditInsufficient):
            _book(member, _class(venue, name="Spin"))

    def test_no_pass_means_insufficient(self):
        venue = _venue()

        with pytest.raises(CreditInsufficient):
            _book(_user("broke"), _class(venue))

    def test_expired_and_depleted_refuse(self):
        venue = _venue()
        member = _user("m1")
        expired = issue_pass(member, _product(venue, name="exp"))
        expired.valid_until = timezone.now() - timedelta(seconds=1)
        expired.save()
        single = issue_pass(member, _product(venue, name="one", credits=1))
        _book(member, _class(venue), key="first")

        with pytest.raises(CreditInsufficient):
            _book(member, _class(venue, name="Spin2"), key="second")
        assert expired.credits_used == 0
        single.refresh_from_db()
        assert single.status == MemberPass.Status.DEPLETED

    def test_ledger_invariant_on_seed(self):
        venue = _venue()
        member = _user("m1")
        for name in ("a", "b"):
            issue_pass(member, _product(venue, name=name))
        _book(member, _class(venue))

        for member_pass in MemberPass.objects.all():
            total = member_pass.credits_total or 0
            summed = member_pass.entries.aggregate(total=Sum("delta"))["total"] or 0
            assert summed == total - member_pass.credits_used


class TestRefundAdjustExpire:
    def test_refund_restores(self):
        venue = _venue()
        member = _user("m1")
        member_pass = issue_pass(member, _product(venue))
        booking = _book(member, _class(venue))

        refund_credit(booking)

        member_pass.refresh_from_db()
        assert member_pass.credits_used == 0
        assert member_pass.entries.filter(reason="refund").count() == 1

    def test_refund_unlimited_is_noop(self):
        venue = _venue()
        member = _user("m2")
        member_pass = issue_pass(member, _product(venue, credits=None))
        booking = _book(member, _class(venue))
        assert booking.credit_tx is None

        assert refund_credit(booking) is None

        assert member_pass.entries.count() == 0

    def test_refund_reactivates_depleted_pass(self):
        venue = _venue()
        member = _user("m3")
        member_pass = issue_pass(member, _product(venue, credits=1))
        booking = _book(member, _class(venue))
        member_pass.refresh_from_db()
        assert member_pass.status == MemberPass.Status.DEPLETED

        refund_credit(booking)

        member_pass.refresh_from_db()
        assert member_pass.status == MemberPass.Status.ACTIVE
        assert member_pass.credits_used == 0

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
        _book(member, _class(venue))
        member_pass.valid_until = timezone.now() - timedelta(seconds=1)
        member_pass.save()

        expire_passes()

        member_pass.refresh_from_db()
        assert member_pass.status == MemberPass.Status.EXPIRED
        summed = member_pass.entries.aggregate(total=Sum("delta"))["total"]
        assert summed == 0


@pytest.mark.django_db(transaction=True)
class TestLastCreditRace:
    def test_twenty_threads_one_credit_yields_one_booking(self):
        venue = _venue(slug="race")
        member = _user("racer")
        issue_pass(member, _product(venue, credits=1))
        classes = [_class(venue, name=f"C{i}") for i in range(20)]

        def attempt(index):
            try:
                _book(member, classes[index], key=f"race-{index}")
                return "booked"
            except CreditInsufficient:
                return "empty"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(attempt, range(20)))

        assert outcomes.count("booked") == 1
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
        issue_pass(member, _product(venue))
        _book(member, _class(venue))

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

    def test_override_cancel_stores_note_on_refund(self):
        from booking.cancellations import cancel_booking
        from passes.models import CreditLedger

        venue = _venue("note-cancel")
        member = _user("noted-cancel")
        issue_pass(member, _product(venue))
        booking = _book(member, _class(venue))

        cancel_booking(
            _user("boss-note"), booking, staff_override=True, reason="desk-override"
        )

        refund = CreditLedger.objects.get(booking=booking, reason="refund")
        assert refund.note == "desk-override"
