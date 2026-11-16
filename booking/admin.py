from django.contrib import admin
from django.db.models import Q
from django.template.response import TemplateResponse
from django.urls import path

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
    list_display = (
        "organization",
        "tier",
        "late_cancel_hours",
        "enforcement",
    )
    list_filter = ("enforcement", "tier")

    def scope_q(self, request):
        # Tier rows are org-level: visible when their org is visible.
        venues = scoped_venues(request)
        return Q(organization__in=venues.values("organization"))

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "coverage/",
                self.admin_site.admin_view(self.coverage_view),
                name="booking_cancellationpolicy_coverage",
            )
        ]
        return custom + urls

    def coverage_view(self, request):
        """Tier matrix: the winning rule per tier (the trio always covers)."""
        context = dict(
            self.admin_site.each_context(request),
            title="Coverage matrix",
            rows=_matrix_rows(),
        )
        return TemplateResponse(request, "admin/booking/coverage.html", context)


def _matrix_rows():
    from organizations.models import Organization

    rows = []
    orgs = Organization.objects.order_by("slug")
    for org in orgs:
        rows.extend(_org_rows(org))
    return rows


def _org_rows(org):
    from passes.models import PlanTier

    return [_coverage_row(org, tier) for tier in PlanTier.values]


def _coverage_row(org, tier):
    from booking.policies import resolve_policy
    from common.ids import OrgId

    policy = resolve_policy(OrgId(org.pk), tier)
    return {
        "organization": org.slug,
        "tier": tier,
        "rule": _winner_label(policy),
    }


def _winner_label(policy):
    rule = f"rule #{policy.pk}"
    return f"{rule} ({policy.tier}, {policy.enforcement})"


@admin.register(CancellationRecord, site=bookr_site)
class CancellationRecordAdmin(ReadOnlyAdmin):
    venue_path = "booking__session__offering__venue"
    list_display = ("booking", "cause", "enforcement_applied", "created_at")
    list_filter = ("cause", "enforcement_applied")
    date_hierarchy = "created_at"
