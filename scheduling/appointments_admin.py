from django.contrib import admin

from organizations.admin_mixins import VenueScopedAdmin, bookr_site
from scheduling.appointments import (
    Appointment,
    AvailabilityException,
    AvailabilityRule,
    Resource,
)


@admin.register(Resource, site=bookr_site)
class ResourceAdmin(VenueScopedAdmin):
    list_display = ("name", "venue", "type")
    list_filter = ("venue", "type")


@admin.register(AvailabilityRule, site=bookr_site)
class AvailabilityRuleAdmin(VenueScopedAdmin):
    venue_path = "resource__venue"
    list_display = ("resource", "weekday", "start_time", "end_time")


@admin.register(AvailabilityException, site=bookr_site)
class AvailabilityExceptionAdmin(VenueScopedAdmin):
    venue_path = "resource__venue"
    list_display = ("resource", "date", "closed")


@admin.register(Appointment, site=bookr_site)
class AppointmentAdmin(VenueScopedAdmin):
    list_display = ("member", "teacher", "venue", "starts_at", "status")
    list_filter = ("venue", "status")
    date_hierarchy = "starts_at"
