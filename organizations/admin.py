"""Back-office admin: OrgRole rows are the single source of truth —
Django Groups are never consulted. Owner/manager get the full
back-office; frontdesk keeps view+change as a desk fallback; teacher/member
never enter, even with is_staff set or inside a Group."""

from django.contrib import admin
from django.db.models import Q

from organizations.admin_mixins import VenueScopedAdmin, bookr_site, scoped_venues
from organizations.models import Organization, OrgRole, Venue


@admin.register(Organization, site=bookr_site)
class OrganizationAdmin(VenueScopedAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")

    def scope_q(self, request):
        orgs = OrgRole.objects.filter(user=request.user).values("organization")
        return Q(pk__in=orgs)


@admin.register(Venue, site=bookr_site)
class VenueAdmin(VenueScopedAdmin):
    list_display = ("name", "organization", "slug")
    list_filter = ("organization",)
    search_fields = ("name", "slug")

    def scope_q(self, request):
        return Q(pk__in=scoped_venues(request))


@admin.register(OrgRole, site=bookr_site)
class OrgRoleAdmin(VenueScopedAdmin):
    venue_path = "venue"
    list_display = ("user", "organization", "venue", "role")
    list_filter = ("organization", "role")
    search_fields = ("user__username",)

    def scope_q(self, request):
        venues = scoped_venues(request)
        return Q(venue__in=venues) | Q(
            venue__isnull=True,
            organization__in=venues.values("organization"),
        )
