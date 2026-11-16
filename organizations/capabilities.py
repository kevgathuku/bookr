"""Capability predicates: the single place that interprets rank.

Gates reference these capabilities, never role values. Rank sets live here
so adding a rank touches exactly one module (ADR-0007).
"""

from organizations.models import OrgRole

OPERATE_DESK_ROLES = frozenset(
    (OrgRole.Role.OWNER, OrgRole.Role.MANAGER, OrgRole.Role.FRONTDESK)
)
MANAGE_ROLES = frozenset((OrgRole.Role.OWNER, OrgRole.Role.MANAGER))
DOOR_STAFF_ROLES = frozenset(
    (
        OrgRole.Role.OWNER,
        OrgRole.Role.MANAGER,
        OrgRole.Role.TEACHER,
        OrgRole.Role.FRONTDESK,
    )
)


def roles_for(user, venue) -> set[str]:
    """Role values the user holds covering the venue (pinned or org-wide)."""
    return set(
        OrgRole.objects.filter(user=user).covering(venue).values_list("role", flat=True)
    )


def is_staff(roles) -> bool:
    """Any non-member role. The broadest gate: prefer a specific
    capability (desk, door, waive) and reach for this only when the
    check genuinely precedes a narrower one."""
    return any(role != OrgRole.Role.MEMBER for role in roles)


def can_operate_desk(roles) -> bool:
    return bool(set(roles) & OPERATE_DESK_ROLES)


def can_manage_staff(roles) -> bool:
    return bool(set(roles) & MANAGE_ROLES)


def can_waive(roles) -> bool:
    """Today identical to desk operation; kept separate so per-user
    granularity (e.g. senior frontdesk) can diverge without touching gates."""
    return bool(set(roles) & OPERATE_DESK_ROLES)


def can_staff_door(roles) -> bool:
    """Operate the door: check members in, mark no-shows. Acting on other
    people's bookings, not entering on your own."""
    return bool(set(roles) & DOOR_STAFF_ROLES)


def is_duty_staff(roles) -> bool:
    """Enter free: duty staff pass the door with no pass or booking.
    Today identical to door operation; kept separate so entry privilege
    and operator authority can diverge without touching gates."""
    return bool(set(roles) & DOOR_STAFF_ROLES)
