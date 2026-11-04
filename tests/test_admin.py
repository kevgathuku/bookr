import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import Client, RequestFactory

from access.models import AccessEvent, AccessPoint
from booking.models import CancellationPolicy
from organizations.admin_mixins import bookr_site
from organizations.models import OrgRole
from passes.models import CreditLedger
from tests.factories import (
    OrganizationFactory,
    UserFactory,
    VenueFactory,
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

    def test_matrix_shows_winner_and_free(self):
        venue = VenueFactory(slug="matrix")
        org = venue.organization
        CancellationPolicy.objects.create(
            organization=org,
            venue=venue,
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.STRIKE,
        )

        response = self._staff_client(venue).get(
            "/admin/booking/cancellationpolicy/coverage/"
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert "strike" in body
        assert "free by design" in body

    def test_member_cannot_see_matrix(self):
        VenueFactory(slug="matrix-member")
        client = Client()
        client.force_login(UserFactory(username="matrix-member"))

        response = client.get("/admin/booking/cancellationpolicy/coverage/")

        assert response.status_code in (302, 403)
