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
        """Venue x category x plan-type matrix: the winning rule per
        context, or free by design where nothing matches but the baseline."""
        context = dict(
            self.admin_site.each_context(request),
            title="Coverage matrix",
            rows=_matrix_rows(),
        )
        return TemplateResponse(request, "admin/booking/coverage.html", context)

    def _scope_q(self, request):
        # Org-wide rules have no venue; visible when their org is visible.
        venues = scoped_venues(request)
        return Q(venue__in=venues) | Q(
            venue__isnull=True, organization__in=venues.values("organization")
        )


def _matrix_rows():
    from organizations.models import Organization

    rows = []
    orgs = Organization.objects.order_by("slug").prefetch_related("venues")
    for org in orgs:
        rows.extend(_org_rows(org))
    return rows


def _org_rows(org):
    return [
        _coverage_row(org, venue, category, plan)
        for venue, category, plan in _coverage_combos(org)
    ]


def _coverage_combos(org):
    import itertools

    from passes.models import PlanType
    from scheduling.catalogue import ClassCategory

    venues = [None, *sorted(org.venues.all(), key=lambda venue: venue.slug)]
    categories = [None, *ClassCategory.values]
    plans = [None, *PlanType.values]
    return itertools.product(venues, categories, plans)


def _coverage_row(org, venue, category, plan):
    from booking.policies import resolve_policy

    if venue is None:
        venue_id, venue_slug = None, "any"
    else:
        venue_id, venue_slug = venue.pk, venue.slug
    policy = resolve_policy(org.pk, venue_id, category, plan)
    return {
        "organization": org.slug,
        "venue": venue_slug,
        "category": category or "any",
        "plan": plan or "any",
        "rule": _winner_label(policy),
    }


def _winner_label(policy):
    if not policy.specificity:
        return "free by design"
    rule = f"rule #{policy.pk}"
    detail = f"{policy.specificity} scopes, {policy.enforcement}"
    return f"{rule} ({detail})"


@admin.register(CancellationRecord, site=bookr_site)
class CancellationRecordAdmin(ReadOnlyAdmin):
    venue_path = "booking__session__offering__venue"
    list_display = ("booking", "cause", "enforcement_applied", "created_at")
    list_filter = ("cause", "enforcement_applied")
    date_hierarchy = "created_at"
