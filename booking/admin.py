from django.contrib import admin

from booking.models import Booking
from organizations.admin_mixins import VenueScopedAdmin, bookr_site


@admin.register(Booking, site=bookr_site)
class BookingAdmin(VenueScopedAdmin):
    venue_path = "session__offering__venue"
    list_display = ("member", "status", "created_at")
    list_filter = ("status",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
