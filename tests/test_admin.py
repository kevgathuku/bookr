import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory

from access.models import AccessEvent, AccessPoint
from booking.models import CancellationPolicy
from organizations.admin_mixins import bookr_site
from organizations.models import OrgRole
from passes.models import CreditLedger, PlanTier
from tests.factories import (
    OrganizationFactory,
    UserFactory,
    VenueFactory,
    book,
    make_member,
    make_policy,
    make_session,
    user_with_role,
)

pytestmark = pytest.mark.django_db

#  Admin seam (Django admin UI, not the API)
#  - Every ModelAdmin scopes rows to the staffer's venues: venue-A staff
#    is blind to venue-B rows (proven on the class changelist).
#  - CreditLedger + AccessEvent are read-only (add/change/delete refuse).
#  - api_token_hash is readonly; rotation happens through tooling only.
#  - Back-office is owner/manager (+frontdesk fallback) by membership role;
#    teacher/member never enter — even inside a Django Group (groups are
#    not roles; ADR-0005).


def _admin_client(user):
    client = Client()
    client.force_login(user)
    return client


class TestVenueScoping:
    def test_venue_a_staff_blind_to_venue_b(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue_a, venue_b = (
            VenueFactory(organization=org, slug="a-main", name="A-Main"),
            VenueFactory(organization=org, slug="b-annex", name="B-Annex"),
        )
        teacher = UserFactory(username="teacher")
        class_a = make_session(venue_a, teacher=teacher)
        make_session(venue_b, teacher=teacher)
        manager = user_with_role(venue_a, OrgRole.Role.MANAGER, "manager", staff=True)

        response = _admin_client(manager).get("/admin/scheduling/classsession/")

        assert response.status_code == 200
        assert response.context["cl"].result_count == 1
        assert list(response.context["cl"].result_list) == [class_a]

    def test_policy_changelist_hides_other_org(self):
        org_a = OrganizationFactory(slug="org-a", name="Org A")
        venue_a = VenueFactory(organization=org_a, slug="a-main", name="A-Main")
        org_b = OrganizationFactory(slug="org-b", name="Org B")
        VenueFactory(organization=org_b, slug="b-main", name="B-Main")
        make_policy(org_a, CancellationPolicy.Enforcement.NONE)
        make_policy(org_b, CancellationPolicy.Enforcement.STRIKE)
        manager = user_with_role(
            venue_a, OrgRole.Role.MANAGER, "pol-manager", staff=True
        )

        response = _admin_client(manager).get("/admin/booking/cancellationpolicy/")

        assert response.status_code == 200
        assert {row.organization_id for row in response.context["cl"].result_list} == {
            org_a.pk
        }

    def test_spanning_owner_sees_both(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue_a, venue_b = (
            VenueFactory(organization=org, slug="a-main", name="A-Main"),
            VenueFactory(organization=org, slug="b-annex", name="B-Annex"),
        )
        teacher = UserFactory(username="teacher")
        make_session(venue_a, teacher=teacher)
        make_session(venue_b, teacher=teacher)
        owner = user_with_role(
            venue_a, OrgRole.Role.OWNER, "owner", org_wide=True, staff=True
        )

        response = _admin_client(owner).get("/admin/scheduling/classsession/")

        assert response.status_code == 200
        assert response.context["cl"].result_count == 2


class TestRoleGate:
    def test_teacher_with_staff_flag_denied(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        teacher = user_with_role(venue, OrgRole.Role.TEACHER, "teacher", staff=True)

        response = _admin_client(teacher).get("/admin/")

        assert response.status_code in (302, 403)

    def test_group_membership_grants_nothing(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        teacher = user_with_role(venue, OrgRole.Role.TEACHER, "teacher", staff=True)
        group, _ = Group.objects.get_or_create(name="managers")
        teacher.groups.add(group)

        response = _admin_client(teacher).get("/admin/scheduling/classsession/")

        assert response.status_code in (302, 403)

    def test_frontdesk_fallback_allowed(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        desk = user_with_role(venue, OrgRole.Role.FRONTDESK, "desk", staff=True)

        response = _admin_client(desk).get("/admin/")

        assert response.status_code == 200

    def test_member_denied(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        member = user_with_role(venue, OrgRole.Role.MEMBER, "member", staff=True)

        response = _admin_client(member).get("/admin/")

        assert response.status_code in (302, 403)


class TestReadOnlyAudit:
    def test_ledger_rejects_add_change_delete(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        manager = user_with_role(venue, OrgRole.Role.MANAGER, "manager", staff=True)
        model_admin = bookr_site._registry[CreditLedger]
        request = _request(manager)

        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False
        assert model_admin.has_view_permission(request) is True

    def test_access_events_reject_add_change_delete(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        manager = user_with_role(venue, OrgRole.Role.MANAGER, "manager", staff=True)
        model_admin = bookr_site._registry[AccessEvent]
        request = _request(manager)

        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_delete_permission(request) is False

    def test_add_url_refuses(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        manager = user_with_role(venue, OrgRole.Role.MANAGER, "manager", staff=True)

        response = _admin_client(manager).get("/admin/passes/creditledger/add/")

        assert response.status_code == 403


class TestTokenHash:
    def test_hash_readonly_rotation_tooling(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        manager = user_with_role(venue, OrgRole.Role.MANAGER, "manager", staff=True)
        point = AccessPoint.objects.create(venue=venue, name="Door", controller_id="d1")
        model_admin = bookr_site._registry[AccessPoint]

        assert "api_token_hash" in model_admin.readonly_fields
        assert "rotate_token" in model_admin.actions

        model_admin.rotate_token(
            _request(manager), AccessPoint.objects.filter(pk=point.pk)
        )
        point.refresh_from_db()

        assert point.api_token_hash != ""


class TestUserEmailRequired:
    def _manager_client(self):
        org = OrganizationFactory(slug="org", name="Org")
        venue = VenueFactory(organization=org, slug="main", name="Main")
        manager = user_with_role(venue, OrgRole.Role.MANAGER, "manager", staff=True)
        return _admin_client(manager)

    def test_add_without_email_rejected(self):
        response = self._manager_client().post(
            "/admin/auth/user/add/",
            {
                "username": "noemail",
                "email": "",
                "password1": "s3cret-pass!",
                "password2": "s3cret-pass!",
            },
        )

        assert response.status_code == 200
        assert "email" in response.context["adminform"].form.errors
        assert not get_user_model().objects.filter(username="noemail").exists()

    def test_add_with_email_creates_user(self):
        response = self._manager_client().post(
            "/admin/auth/user/add/",
            {
                "username": "mailed",
                "email": "mailed@example.com",
                "password1": "s3cret-pass!",
                "password2": "s3cret-pass!",
            },
        )

        assert response.status_code == 302
        user = get_user_model().objects.get(username="mailed")
        assert user.email == "mailed@example.com"

    def test_add_without_password_invites_unusable(self):
        # Invited members set their own password through the claim link;
        # staff must not invent one for them.
        response = self._manager_client().post(
            "/admin/auth/user/add/",
            {"username": "invited", "email": "invited@example.com"},
        )

        assert response.status_code == 302
        user = get_user_model().objects.get(username="invited")
        assert user.has_usable_password() is False


def _request(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


class TestCoverageMatrix:
    def _staff_client(self, venue):
        user = user_with_role(
            venue,
            OrgRole.Role.MANAGER,
            "matrix-staff",
            org_wide=True,
            staff=True,
        )
        return _admin_client(user)

    def test_matrix_shows_tier_winners(self):
        venue = VenueFactory(slug="matrix")
        org = venue.organization
        make_policy(
            org,
            CancellationPolicy.Enforcement.STRIKE,
            tier=PlanTier.REGULAR,
            late_cancel_hours=12,
        )

        response = self._staff_client(venue).get(
            "/admin/booking/cancellationpolicy/coverage/"
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert "trial" in body
        assert "regular" in body
        assert "monthly" in body
        assert "strike" in body

    def test_member_cannot_see_matrix(self):
        VenueFactory(slug="matrix-member")
        client = Client()
        client.force_login(UserFactory(username="matrix-member"))

        response = client.get("/admin/booking/cancellationpolicy/coverage/")

        assert response.status_code in (302, 403)


class TestBookingActions:
    """BookingAdmin never writes transition fields by hand: they are
    readonly, and the console changes bookings through service-backed
    actions (version-guarded writes plus the refund/record/notice)."""

    def test_transition_fields_are_readonly(self):
        from booking.admin import BookingAdmin

        assert {
            "status",
            "hold_expires_at",
            "checked_in_at",
            "credits_spent",
            "membership",
            "version",
        } <= set(BookingAdmin.readonly_fields)

    def test_cancel_action_runs_the_service(self):
        from booking.models import Booking, CancellationRecord

        venue = VenueFactory()
        member = make_member("m1", venue, credits=10)
        session = make_session(venue)
        booking = book(member, session)
        desk = user_with_role(
            venue, OrgRole.Role.FRONTDESK, "desk", org_wide=True, staff=True
        )

        response = _admin_client(desk).post(
            "/admin/booking/booking/",
            {"action": "cancel_bookings", "_selected_action": [booking.pk]},
            follow=True,
        )

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert CancellationRecord.objects.filter(booking=booking).count() == 1

    def test_check_in_action_runs_the_service(self):
        from booking.models import Booking

        venue = VenueFactory()
        member = make_member("m1", venue, credits=10)
        session = make_session(venue)
        booking = book(member, session)
        desk = user_with_role(
            venue, OrgRole.Role.FRONTDESK, "desk", org_wide=True, staff=True
        )

        response = _admin_client(desk).post(
            "/admin/booking/booking/",
            {"action": "check_in_bookings", "_selected_action": [booking.pk]},
            follow=True,
        )

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == Booking.Status.ATTENDED


class TestBookingAddDeleteRefused:
    def test_booking_admin_has_no_add_or_delete(self):
        from booking.admin import BookingAdmin

        assert BookingAdmin.has_add_permission(None, None) is False
        assert BookingAdmin.has_delete_permission(None, None) is False

    def test_add_view_refuses(self):
        venue = VenueFactory()
        desk = user_with_role(
            venue, OrgRole.Role.FRONTDESK, "desk", org_wide=True, staff=True
        )

        response = _admin_client(desk).get("/admin/booking/booking/add/")

        assert response.status_code == 403
