"""Venue-membership API guard. 404s, never 403s (no id leaks)."""

from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied

from organizations.tenancy import STAFF_ROLES, _covers, _ensure_venue


def staff_covering(request, venue):
    """True when the user holds a staff role covering the venue."""
    return any(
        membership.role in STAFF_ROLES and _covers(membership, venue)
        for membership in getattr(request, "memberships", ())
    )


class IsVenueMember(permissions.BasePermission):
    """Filter-then-404: membership covering request.venue, else NotFound."""

    message = "No such venue."

    def has_permission(self, request, view):
        venue = _ensure_venue(request)
        if venue is None or not request.user.is_authenticated:
            raise NotFound(self.message)
        for membership in getattr(request, "memberships", ()):
            if _covers(membership, venue):
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
