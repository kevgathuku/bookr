"""Back-office building blocks: role-based model permissions plus
per-venue row scoping. OrgRole rows are the single source of truth —
Django Groups are never consulted."""

from django.contrib import admin
from django.db.models import Q

from organizations.capabilities import (
    MANAGE_ROLES,
    OPERATE_DESK_ROLES,
    can_manage_staff,
    can_operate_desk,
)
from organizations.models import OrgRole, Venue


class BookrAdminSite(admin.AdminSite):
    site_header = "Bookr back-office"

    def has_permission(self, request):
        if not super().has_permission(request):
            return False
        if request.user.is_superuser:
            return True
        if not request.user.is_active:
            return False
        return OrgRole.objects.filter(
            user=request.user, role__in=OPERATE_DESK_ROLES
        ).exists()


bookr_site = BookrAdminSite(name="bookr")


def _org_roles(request):
    """OrgRole rows, once per request (middleware already fetched them
    for session users; the fallback queries a single time)."""
    cached = getattr(request, "org_role_rows", None)
    if cached is None:
        cached = list(
            OrgRole.objects.filter(user=request.user).select_related(
                "venue", "organization"
            )
        )
        request.org_role_rows = cached
    return cached


def staff_roles(request):
    if request.user.is_superuser:
        return set(MANAGE_ROLES)
    return {row.role for row in _org_roles(request)}


def scoped_venues(request):
    """Venues the user covers: pinned plus spanning-org venues."""
    roles = _org_roles(request)
    pinned = [row.venue_id for row in roles if row.venue_id is not None]
    orgs = {row.organization_id for row in roles if row.venue_id is None}
    return Venue.objects.filter(Q(pk__in=pinned) | Q(organization__in=orgs))


class VenueScopedAdmin(admin.ModelAdmin):
    """Per-venue rows + role-based model perms. venue_path locates the venue."""

    venue_path = "venue"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(self.scope_q(request))

    def has_view_permission(self, request, obj=None):
        return can_operate_desk(staff_roles(request))

    def has_add_permission(self, request):
        return can_manage_staff(staff_roles(request))

    def has_change_permission(self, request, obj=None):
        # Desk fallback: view + change, never add/delete.
        return can_operate_desk(staff_roles(request))

    def has_delete_permission(self, request, obj=None):
        return can_manage_staff(staff_roles(request))

    def scope_q(self, request):
        return Q(**{f"{self.venue_path}__in": scoped_venues(request)})


class ReadOnlyAdmin(VenueScopedAdmin):
    """Audit tables: view for the back-office, never add/change/delete."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
