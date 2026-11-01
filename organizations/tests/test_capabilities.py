import pytest

from organizations.capabilities import (  # noqa: WPS235 — capability matrix tests import every predicate plus the rank sets
    DOOR_STAFF_ROLES,
    MANAGE_ROLES,
    OPERATE_DESK_ROLES,
    can_manage_staff,
    can_operate_desk,
    can_staff_door,
    can_waive,
    is_duty_staff,
    roles_for,
)
from organizations.models import OrgRole
from tests.factories import UserFactory, VenueFactory, user_with_role, user_with_roles

pytestmark = pytest.mark.django_db


class TestRolesFor:
    def test_collects_pinned_and_org_wide_roles(self):
        venue = VenueFactory()
        user = user_with_roles(
            venue,
            [(OrgRole.Role.MEMBER, True), (OrgRole.Role.TEACHER, False)],
        )

        assert roles_for(user, venue) == {"member", "teacher"}

    def test_ignores_other_venues_and_orgs(self):
        venue = VenueFactory()
        other = VenueFactory()

        user = user_with_role(venue, OrgRole.Role.MEMBER)

        assert roles_for(user, other) == set()

    def test_pinned_role_does_not_leak_to_sibling_venue(self):
        venue = VenueFactory()
        sibling = VenueFactory(organization=venue.organization)

        user = user_with_role(venue, OrgRole.Role.MEMBER)

        assert roles_for(user, venue) == {"member"}
        assert roles_for(user, sibling) == set()

    def test_org_wide_role_covers_every_venue(self):
        venue = VenueFactory()
        sibling = VenueFactory(organization=venue.organization)

        user = user_with_role(venue, OrgRole.Role.FRONTDESK, "frontdesk", True)

        assert roles_for(user, venue) == {"frontdesk"}
        assert roles_for(user, sibling) == {"frontdesk"}

    def test_no_roles_is_empty(self):
        assert roles_for(UserFactory(), VenueFactory()) == set()


class TestCapabilities:
    # sorted: frozenset order varies per process (hash seed) and breaks
    # xdist, which requires identical collection on every worker.
    @pytest.mark.parametrize("role", sorted(OPERATE_DESK_ROLES))
    def test_desk_is_frontdesk_and_up(self, role):
        assert can_operate_desk({role})

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            ("manager", True),
            ("owner", True),
            ("frontdesk", True),
            ("teacher", False),
            ("member", False),
        ],
    )
    def test_desk_excludes_teaching_and_plain_members(self, role, allowed):
        assert can_operate_desk({role}) is allowed
        assert not can_operate_desk(set())

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            ("manager", True),
            ("owner", True),
            ("frontdesk", False),
            ("teacher", False),
            ("member", False),
        ],
    )
    def test_manage_is_manager_and_up(self, role, allowed):
        assert can_manage_staff({role}) is allowed

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            ("manager", True),
            ("owner", True),
            ("frontdesk", False),
            ("teacher", False),
            ("member", False),
        ],
    )
    def test_waive_matches_desk(self, role, allowed):
        assert can_manage_staff({role}) is allowed
        assert not can_waive(set())

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            ("teacher", True),
            ("manager", True),
            ("owner", True),
            ("frontdesk", True),
            ("member", False),
        ],
    )
    def test_door_staff_excludes_plain_members(self, role, allowed):
        assert can_staff_door({role}) is allowed
        assert not can_staff_door(set())

    @pytest.mark.parametrize(
        ("role", "allowed"),
        [
            ("teacher", True),
            ("manager", True),
            ("owner", True),
            ("frontdesk", True),
            ("member", False),
        ],
    )
    def test_duty_staff_enters_free(self, role, allowed):
        assert is_duty_staff({role}) is allowed
        assert not is_duty_staff(set())

    def test_rank_sets_nest(self):
        assert MANAGE_ROLES <= OPERATE_DESK_ROLES <= DOOR_STAFF_ROLES

    def test_owner_in_all_rank_sets(self):
        assert OrgRole.Role.OWNER in MANAGE_ROLES
        assert OrgRole.Role.OWNER in OPERATE_DESK_ROLES
        assert OrgRole.Role.OWNER in DOOR_STAFF_ROLES

    def test_member_in_no_rank_set(self):
        assert OrgRole.Role.MEMBER not in MANAGE_ROLES
        assert OrgRole.Role.MEMBER not in OPERATE_DESK_ROLES
        assert OrgRole.Role.MEMBER not in DOOR_STAFF_ROLES

    @pytest.mark.parametrize("role", OrgRole.Role.values)
    def test_waive_matches_desk_for_every_role(self, role):
        assert can_waive({role}) == can_operate_desk({role})

    @pytest.mark.parametrize("role", OrgRole.Role.values)
    def test_duty_staff_matches_door_operators_for_every_role(self, role):
        assert is_duty_staff({role}) == can_staff_door({role})
