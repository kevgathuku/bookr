"""Partner-global models: no venue to scope by, so plain ModelAdmin
under the role-gated site; log rows are append-only."""

from django.contrib import admin

from aggregators.models import Aggregator, AggregatorBooking, AggregatorEventLog
from organizations.admin_mixins import bookr_site


@admin.register(Aggregator, site=bookr_site)
class AggregatorAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "seat_allotment", "active")
    list_filter = ("active",)
    readonly_fields = ("api_token_hash",)


class AppendOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AggregatorBooking, site=bookr_site)
class AggregatorBookingAdmin(AppendOnlyAdmin):
    list_display = ("aggregator", "external_id", "booking")


@admin.register(AggregatorEventLog, site=bookr_site)
class AggregatorEventLogAdmin(AppendOnlyAdmin):
    list_display = ("aggregator", "method", "path", "status_code", "created_at")
    list_filter = ("status_code",)
    date_hierarchy = "created_at"
