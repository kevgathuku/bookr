"""Back-office admin: membership roles are the single source of truth
(ADR-0005) — Django Groups are never consulted. Owner/manager get the full
back-office; frontdesk keeps view+change as a desk fallback; teacher/member
never enter, even with is_staff set or inside a Group."""

from django.contrib import admin
from django.db.models import Q

from organizations.admin_mixins import VenueScopedAdmin, bookr_site, scoped_venues
from organizations.models import Membership, Organization, Venue, VenuePolicy


class VenuePolicyInline(admin.TabularInline):
    model = VenuePolicy
    extra = 0
    fields = ("valid_from", "valid_until", "class_late_cancel_hours")
    readonly_fields = ("valid_from",)
    show_change_link = True


@admin.register(Organization, site=bookr_site)
class OrganizationAdmin(VenueScopedAdmin):
    list_display = ("name", "slug", "membership_scope")
    list_filter = ("membership_scope",)
    search_fields = ("name", "slug")

    def _scope_q(self, request):
        orgs = Membership.objects.filter(user=request.user).values("organization")
        return Q(pk__in=orgs)


@admin.register(Venue, site=bookr_site)
class VenueAdmin(VenueScopedAdmin):
    list_display = ("name", "organization", "slug")
    list_filter = ("organization",)
    search_fields = ("name", "slug")
    inlines = (VenuePolicyInline,)

    def _scope_q(self, request):
        return Q(pk__in=scoped_venues(request))


@admin.register(VenuePolicy, site=bookr_site)
class VenuePolicyAdmin(VenueScopedAdmin):
    list_display = ("venue", "valid_from", "valid_until")
    list_filter = ("venue__organization",)
    readonly_fields = ("valid_from",)


@admin.register(Membership, site=bookr_site)
class MembershipAdmin(VenueScopedAdmin):
    list_display = ("user", "organization", "venue", "role")
    list_filter = ("organization", "role")
    search_fields = ("user__username",)

    def _scope_q(self, request):
        venues = scoped_venues(request)
        orgs = Membership.objects.filter(user=request.user).values("organization")
        return Q(venue__in=venues) | Q(venue__isnull=True, organization__in=orgs)
