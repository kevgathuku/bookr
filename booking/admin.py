from django.contrib import admin

from booking.models import Booking
from organizations.admin_mixins import VenueScopedAdmin, bookr_site


@admin.register(Booking, site=bookr_site)
class BookingAdmin(VenueScopedAdmin):
    list_display = ("member", "venue", "status", "created_at")
    list_filter = ("venue", "status")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
