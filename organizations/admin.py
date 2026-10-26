from django.contrib import admin

from .models import Membership, Organization, Venue, VenuePolicy


class VenueInline(admin.TabularInline):
    model = Venue
    extra = 0
    fields = ("name", "slug", "time_zone")
    show_change_link = True


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fields = ("user", "venue", "role")
    autocomplete_fields = ("user",)


class VenuePolicyInline(admin.TabularInline):
    model = VenuePolicy
    extra = 0
    fields = ("valid_from", "valid_until", "class_late_cancel_hours")
    readonly_fields = ("valid_from",)
    show_change_link = True


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "membership_scope")
    list_filter = ("membership_scope",)
    search_fields = ("name", "slug")
    inlines = (VenueInline, MembershipInline)


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "slug")
    list_filter = ("organization",)
    search_fields = ("name", "slug")
    inlines = (VenuePolicyInline,)


@admin.register(VenuePolicy)
class VenuePolicyAdmin(admin.ModelAdmin):
    list_display = ("venue", "valid_from", "valid_until")
    list_filter = ("venue__organization",)
    readonly_fields = ("valid_from",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "venue", "role")
    list_filter = ("organization", "role")
    search_fields = ("user__username",)
    autocomplete_fields = ("user",)
