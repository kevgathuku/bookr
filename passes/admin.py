from django.contrib import admin

from organizations.admin_mixins import ReadOnlyAdmin, VenueScopedAdmin, bookr_site
from passes.models import CreditLedger, Plan


@admin.register(Plan, site=bookr_site)
class PlanAdmin(VenueScopedAdmin):
    list_display = (
        "name",
        "organization",
        "plan_type",
        "entitlement",
        "validity",
        "duration_days",
    )
    list_filter = ("plan_type", "entitlement", "validity")

    def scope_q(self, request):
        # Plans are org-wide; visible when their org is visible.
        from django.db.models import Q

        from organizations.admin_mixins import scoped_venues

        venues = scoped_venues(request)
        return Q(organization__in=venues.values("organization"))


@admin.register(CreditLedger, site=bookr_site)
class CreditLedgerAdmin(ReadOnlyAdmin):
    list_display = ("membership", "delta", "reason", "created_at")
    list_filter = ("reason",)
    date_hierarchy = "created_at"

    def scope_q(self, request):
        # Entries are org-wide like plans; visible when their org is visible.
        from django.db.models import Q

        from organizations.admin_mixins import scoped_venues

        venues = scoped_venues(request)
        return Q(membership__plan__organization__in=venues.values("organization"))
