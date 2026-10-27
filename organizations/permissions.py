"""Venue-membership API guard. 404s, never 403s (no id leaks)."""

from rest_framework import permissions
from rest_framework.exceptions import NotFound

from organizations.tenancy import STAFF_ROLES, _covers, _ensure_venue


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
        staff_present = any(
            membership.role in STAFF_ROLES and _covers(membership, venue)
            for membership in getattr(request, "memberships", ())
        )
        return staff_present
