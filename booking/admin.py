from django.contrib import admin
from django.db.models import Q

from booking.models import Booking, CancellationPolicy, CancellationRecord
from organizations.admin_mixins import (
    ReadOnlyAdmin,
    VenueScopedAdmin,
    bookr_site,
    scoped_venues,
)


@admin.register(Booking, site=bookr_site)
class BookingAdmin(VenueScopedAdmin):
    venue_path = "session__offering__venue"
    list_display = ("member", "status", "created_at")
    list_filter = ("status",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)


@admin.register(CancellationPolicy, site=bookr_site)
class CancellationPolicyAdmin(VenueScopedAdmin):
    venue_path = "venue"
    list_display = (
        "organization",
        "venue",
        "class_category",
        "plan_type",
        "late_cancel_hours",
        "enforcement",
        "priority",
    )
    list_filter = ("enforcement",)

    def _scope_q(self, request):
        # Org-wide rules have no venue; visible when their org is visible.
        venues = scoped_venues(request)
        return Q(venue__in=venues) | Q(
            venue__isnull=True, organization__in=venues.values("organization")
        )


@admin.register(CancellationRecord, site=bookr_site)
class CancellationRecordAdmin(ReadOnlyAdmin):
    venue_path = "booking__session__offering__venue"
    list_display = ("booking", "cause", "enforcement_applied", "created_at")
    list_filter = ("cause", "enforcement_applied")
    date_hierarchy = "created_at"
