import pytest

from organizations.capabilities import (
    can_manage_staff,
    can_operate_desk,
    can_staff_door,
    can_waive,
    roles_for,
)
from organizations.models import OrgRole
from tests.factories import OrgRoleFactory, VenueFactory

pytestmark = pytest.mark.django_db


class TestRolesFor:
    def test_collects_pinned_and_org_wide_roles(self):
        venue = VenueFactory()
        user = OrgRoleFactory(
            organization=venue.organization, venue=None, role=OrgRole.Role.MEMBER
        ).user
        OrgRoleFactory(
            organization=venue.organization,
            venue=venue,
            user=user,
            role=OrgRole.Role.TEACHER,
        )

        assert roles_for(user, venue) == {"member", "teacher"}

    def test_ignores_other_venues_and_orgs(self):
        venue = VenueFactory()
        other = VenueFactory()
        user = OrgRoleFactory(
            organization=venue.organization, venue=venue, role=OrgRole.Role.MEMBER
        ).user

        assert other.pk not in {venue.pk}
        assert roles_for(user, other) == set()


class TestCapabilities:
    def test_desk_is_frontdesk_and_up(self):
        assert can_operate_desk({"frontdesk"})
        assert can_operate_desk({"manager"})
        assert can_operate_desk({"owner"})

    def test_desk_excludes_teaching_and_plain_members(self):
        assert not can_operate_desk({"teacher"})
        assert not can_operate_desk({"member"})
        assert not can_operate_desk(set())

    def test_manage_is_manager_and_up(self):
        assert can_manage_staff({"manager"})
        assert can_manage_staff({"owner"})
        assert not can_manage_staff({"frontdesk"})
        assert not can_manage_staff({"teacher"})
        assert not can_manage_staff({"member"})

    def test_waive_matches_desk(self):
        assert can_waive({"frontdesk"})
        assert can_waive({"owner"})
        assert not can_waive({"teacher"})
        assert not can_waive({"member"})

    def test_door_staff_excludes_plain_members(self):
        assert can_staff_door({"teacher"})
        assert can_staff_door({"frontdesk"})
        assert can_staff_door({"manager"})
        assert can_staff_door({"owner"})
        assert not can_staff_door({"member"})
