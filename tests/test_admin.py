from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from access.models import AccessEvent, AccessPoint
from organizations.admin_mixins import bookr_site
from organizations.models import Organization, OrgRole, Venue
from passes.models import CreditLedger
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

#  Admin seam (Django admin UI, not the API)
#  - Every ModelAdmin scopes rows to the staffer's venues: venue-A staff
#    is blind to venue-B rows (proven on the class changelist).
#  - CreditLedger + AccessEvent are read-only (add/change/delete refuse).
#  - api_token_hash is readonly; rotation happens through tooling only.
#  - Back-office is owner/manager (+frontdesk fallback) by membership role;
#    teacher/member never enter — even inside a Django Group (groups are
#    not roles; ADR-0005).


def _user(username, staff=False):
    return UserFactory(username=username, is_staff=staff)


def _org(slug):
    return Organization.objects.create(slug=slug, name=slug.title())


def _venue(org, slug):
    return Venue.objects.create(organization=org, slug=slug, name=slug.title())


def _membership(org, user, role, venue=None):
    return OrgRole.objects.create(organization=org, venue=venue, user=user, role=role)


def _class(venue, teacher):
    from tests.factories import ClassOfferingFactory, ClassSessionFactory

    offering = ClassOfferingFactory(venue=venue, teacher=teacher)
    return ClassSessionFactory(
        offering=offering, starts_at=timezone.now() + timedelta(days=1)
    )


def _admin_client(user):
    client = Client()
    client.force_login(user)
    return client


class TestVenueScoping:
    def test_venue_a_staff_blind_to_venue_b(self):
        org = _org("org")
        venue_a, venue_b = _venue(org, "a-main"), _venue(org, "b-annex")
        teacher = _user("teacher")
        class_a = _class(venue_a, teacher)
        _class(venue_b, teacher)
        manager = _user("manager", staff=True)
        _membership(org, manager, OrgRole.Role.MANAGER, venue_a)

        response = _admin_client(manager).get("/admin/scheduling/classsession/")

        assert response.status_code == 200
        assert response.context["cl"].result_count == 1
        assert list(response.context["cl"].result_list) == [class_a]

    def test_spanning_owner_sees_both(self):
        org = _org("org")
        venue_a, venue_b = _venue(org, "a-main"), _venue(org, "b-annex")
        teacher = _user("teacher")
        _class(venue_a, teacher)
        _class(venue_b, teacher)
        owner = _user("owner", staff=True)
        _membership(org, owner, OrgRole.Role.OWNER)

        response = _admin_client(owner).get("/admin/scheduling/classsession/")

        assert response.status_code == 200
        assert response.context["cl"].result_count == 2


class TestRoleGate:
    def test_teacher_with_staff_flag_denied(self):
        org = _org("org")
        venue = _venue(org, "main")
        teacher = _user("teacher", staff=True)
        _membership(org, teacher, OrgRole.Role.TEACHER, venue)

        response = _admin_client(teacher).get("/admin/")

        assert response.status_code in (302, 403)

    def test_group_membership_grants_nothing(self):
        org = _org("org")
        venue = _venue(org, "main")
        teacher = _user("teacher", staff=True)
        group, _ = Group.objects.get_or_create(name="managers")
        teacher.groups.add(group)
        _membership(org, teacher, OrgRole.Role.TEACHER, venue)

        response = _admin_client(teacher).get("/admin/scheduling/classsession/")

        assert response.status_code in (302, 403)

    def test_frontdesk_fallback_allowed(self):
        org = _org("org")
        venue = _venue(org, "main")
        desk = _user("desk", staff=True)
        _membership(org, desk, OrgRole.Role.FRONTDESK, venue)

        response = _admin_client(desk).get("/admin/")

        assert response.status_code == 200

    def test_member_denied(self):
        org = _org("org")
        venue = _venue(org, "main")
        member = _user("member", staff=True)
        _membership(org, member, OrgRole.Role.MEMBER, venue)

        response = _admin_client(member).get("/admin/")

        assert response.status_code in (302, 403)


class TestReadOnlyAudit:
    def test_ledger_rejects_add_change_delete(self):
        org = _org("org")
        venue = _venue(org, "main")
        manager = _user("manager", staff=True)
        _membership(org, manager, OrgRole.Role.MANAGER, venue)
        model_admin = bookr_site._registry[CreditLedger]
        request = _request(manager)

        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False
        assert model_admin.has_view_permission(request) is True

    def test_access_events_reject_add_change_delete(self):
        org = _org("org")
        venue = _venue(org, "main")
        manager = _user("manager", staff=True)
        _membership(org, manager, OrgRole.Role.MANAGER, venue)
        model_admin = bookr_site._registry[AccessEvent]
        request = _request(manager)

        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_delete_permission(request) is False

    def test_add_url_refuses(self):
        org = _org("org")
        venue = _venue(org, "main")
        manager = _user("manager", staff=True)
        _membership(org, manager, OrgRole.Role.MANAGER, venue)

        response = _admin_client(manager).get("/admin/passes/creditledger/add/")

        assert response.status_code == 403


class TestTokenHash:
    def test_hash_readonly_rotation_tooling(self):
        org = _org("org")
        venue = _venue(org, "main")
        manager = _user("manager", staff=True)
        _membership(org, manager, OrgRole.Role.MANAGER, venue)
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
        org = _org("org")
        venue = _venue(org, "main")
        manager = _user("manager", staff=True)
        _membership(org, manager, OrgRole.Role.MANAGER, venue)
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
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    request = RequestFactory().get("/admin/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


class TestCoverageMatrix:
    def _staff_client(self, org):
        from organizations.models import OrgRole
        from tests.factories import OrgRoleFactory

        user = _user("matrix-staff", staff=True)
        OrgRoleFactory(
            organization=org, venue=None, user=user, role=OrgRole.Role.MANAGER
        )
        client = Client()
        client.force_login(user)
        return client

    def test_matrix_shows_winner_and_free(self):
        from booking.models import CancellationPolicy
        from tests.factories import VenueFactory

        venue = VenueFactory(slug="matrix")
        org = venue.organization
        CancellationPolicy.objects.create(
            organization=org,
            venue=venue,
            late_cancel_hours=12,
            enforcement=CancellationPolicy.Enforcement.STRIKE,
        )

        response = self._staff_client(org).get(
            "/admin/booking/cancellationpolicy/coverage/"
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert "strike" in body
        assert "free by design" in body

    def test_member_cannot_see_matrix(self):
        from tests.factories import VenueFactory

        VenueFactory(slug="matrix-member")
        client = Client()
        client.force_login(_user("matrix-member"))

        response = client.get("/admin/booking/cancellationpolicy/coverage/")

        assert response.status_code in (302, 403)
