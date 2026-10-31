"""Venue-membership API guard. 404s, never 403s (no id leaks)."""

from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied

from organizations.capabilities import can_operate_desk
from organizations.tenancy import STAFF_ROLES, _covers, _ensure_venue


def _legacy_staff(request, venue):
    """Old-model branch: teaching counts as staff there (kept until contract)."""
    return any(
        mem.role in STAFF_ROLES and _covers(mem, venue)
        for mem in getattr(request, "memberships", ())
    )


def staff_covering(request, venue):
    """True when the user holds a staff role covering the venue.

    Checks both role stores during the expand transition: legacy membership
    rows use the old STAFF_ROLES set (teaching counts as staff there); new
    OrgRole rows go through the desk capability (teaching alone does not).
    The contract ticket drops the legacy branch with the old model.
    """
    if _legacy_staff(request, venue):
        return True
    covered = [
        row.role for row in getattr(request, "org_roles", ()) if _covers(row, venue)
    ]
    return can_operate_desk(covered)


class IsVenueMember(permissions.BasePermission):
    """Filter-then-404: membership covering request.venue, else NotFound."""

    message = "No such venue."

    def has_permission(self, request, view):
        venue = _ensure_venue(request)
        if venue is None or not request.user.is_authenticated:
            raise NotFound(self.message)
        rows = list(getattr(request, "memberships", ())) + list(
            getattr(request, "org_roles", ())
        )
        for row in rows:
            if _covers(row, venue):
                return True
        raise NotFound(self.message)


class IsStaffOrReadOnly(permissions.BasePermission):
    """Publishing (unsafe methods) is staff-only; reads need membership only."""

    message = "Publishing is staff-only."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        venue = _ensure_venue(request)
        if venue is None or not request.user.is_authenticated:
            raise NotFound("No such venue.")
        return staff_covering(request, venue)


class IsStaff(permissions.BasePermission):
    """Back-office: staff-only for reads and writes alike."""

    message = "Staff only."

    def has_permission(self, request, view):
        venue = _ensure_venue(request)
        if venue is None or not request.user.is_authenticated:
            raise NotFound("No such venue.")
        if not staff_covering(request, venue):
            raise PermissionDenied(self.message)
        return True
