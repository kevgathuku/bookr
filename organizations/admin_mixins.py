"""Back-office building blocks: role-based model permissions plus
per-venue row scoping. Membership roles are the single source of truth
(ADR-0005) — Django Groups are never consulted."""

from django.contrib import admin
from django.db.models import Q

from organizations.models import Membership, Venue

BACK_OFFICE_ROLES = ("owner", "manager", "frontdesk")
MANAGE_ROLES = ("owner", "manager")


class BookrAdminSite(admin.AdminSite):
    site_header = "Bookr back-office"

    def has_permission(self, request):
        if not super().has_permission(request):
            return False
        if request.user.is_superuser:
            return True
        return (
            request.user.is_active
            and Membership.objects.filter(
                user=request.user, role__in=BACK_OFFICE_ROLES
            ).exists()
        )


bookr_site = BookrAdminSite(name="bookr")


def _memberships(request):
    """Membership rows, once per request (middleware already fetched them
    for session users; the fallback queries a single time)."""
    cached = getattr(request, "memberships", None)
    if cached is None:
        cached = list(
            Membership.objects.filter(user=request.user).select_related(
                "venue", "organization"
            )
        )
        request.memberships = cached
    return cached


def staff_roles(request):
    if request.user.is_superuser:
        return set(MANAGE_ROLES)
    return {mem.role for mem in _memberships(request)}


def scoped_venues(request):
    """Venues the user covers: pinned plus spanning-org venues."""
    memberships = _memberships(request)
    pinned = [mem.venue_id for mem in memberships if mem.venue_id is not None]
    orgs = {mem.organization_id for mem in memberships if mem.venue_id is None}
    return Venue.objects.filter(Q(pk__in=pinned) | Q(organization__in=orgs))


class VenueScopedAdmin(admin.ModelAdmin):
    """Per-venue rows + role-based model perms. venue_path locates the venue."""

    venue_path = "venue"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(self._scope_q(request))

    def has_view_permission(self, request, obj=None):
        return bool(set(staff_roles(request)) & set(BACK_OFFICE_ROLES))

    def has_add_permission(self, request):
        return bool(set(staff_roles(request)) & set(MANAGE_ROLES))

    def has_change_permission(self, request, obj=None):
        roles = set(staff_roles(request))
        if roles & set(MANAGE_ROLES):
            return True
        # Frontdesk fallback: view + change, never add/delete.
        return "frontdesk" in roles

    def has_delete_permission(self, request, obj=None):
        return bool(set(staff_roles(request)) & set(MANAGE_ROLES))

    def _scope_q(self, request):
        return Q(**{f"{self.venue_path}__in": scoped_venues(request)})


class ReadOnlyAdmin(VenueScopedAdmin):
    """Audit tables: view for the back-office, never add/change/delete."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
