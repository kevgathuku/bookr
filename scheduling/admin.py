from django.contrib import admin

from organizations.admin_mixins import VenueScopedAdmin, bookr_site
from scheduling.models import ClassSession


@admin.register(ClassSession, site=bookr_site)
class ClassSessionAdmin(VenueScopedAdmin):
    venue_path = "offering__venue"
    list_display = ("offering", "starts_at", "capacity", "cancelled_at")
    list_filter = ("offering__category",)
    date_hierarchy = "starts_at"
