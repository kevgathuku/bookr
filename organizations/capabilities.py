"""Capability predicates: the single place that interprets rank.

Gates reference these capabilities, never role values. Rank sets live here
so adding a rank touches exactly one module (ADR-0007).
"""

from django.db.models import Q

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
        OrgRole.objects.filter(user=user, organization_id=venue.organization_id)
        .filter(Q(venue=venue) | Q(venue__isnull=True))
        .values_list("role", flat=True)
    )


def can_operate_desk(roles) -> bool:
    return bool(set(roles) & OPERATE_DESK_ROLES)


def can_manage_staff(roles) -> bool:
    return bool(set(roles) & MANAGE_ROLES)


def can_waive(roles) -> bool:
    """Today identical to desk operation; kept separate so per-user
    granularity (e.g. senior frontdesk) can diverge without touching gates."""
    return bool(set(roles) & OPERATE_DESK_ROLES)


def can_staff_door(roles) -> bool:
    """Any duty role opens doors; plain members enter on pass or booking."""
    return bool(set(roles) & DOOR_STAFF_ROLES)
