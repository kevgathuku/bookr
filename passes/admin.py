from django.contrib import admin

from organizations.admin_mixins import ReadOnlyAdmin, VenueScopedAdmin, bookr_site
from passes.models import CreditLedger, MemberPass, PassProduct, Plan


@admin.register(PassProduct, site=bookr_site)
class PassProductAdmin(VenueScopedAdmin):
    list_display = ("name", "venue", "credits_total")
    list_filter = ("venue",)


@admin.register(Plan, site=bookr_site)
class PlanAdmin(VenueScopedAdmin):
    list_display = ("name", "organization", "plan_type", "validity_days")
    list_filter = ("plan_type",)

    def _scope_q(self, request):
        # Plans are org-wide; visible when their org is visible.
        from django.db.models import Q

        from organizations.admin_mixins import scoped_venues

        venues = scoped_venues(request)
        return Q(organization__in=venues.values("organization"))


@admin.register(MemberPass, site=bookr_site)
class MemberPassAdmin(VenueScopedAdmin):
    venue_path = "product__venue"
    list_display = ("member", "product", "status", "credits_used")
    list_filter = ("status",)
    readonly_fields = ("credits_used",)


@admin.register(CreditLedger, site=bookr_site)
class CreditLedgerAdmin(ReadOnlyAdmin):
    venue_path = "member_pass__product__venue"
    list_display = ("member_pass", "delta", "reason", "created_at")
    list_filter = ("reason",)
    date_hierarchy = "created_at"
