from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.template.response import TemplateResponse
from django.urls import path

from booking.cancellations import cancel_booking, check_in, mark_no_show
from booking.errors import BookingError
from booking.models import Booking, CancellationPolicy, CancellationRecord
from common.ids import BookingId
from organizations.admin_mixins import (
    ReadOnlyAdmin,
    VenueScopedAdmin,
    bookr_site,
    scoped_venues,
)


def _staff_cancel(*, actor, booking):
    cancel_booking(
        booking_id=BookingId(booking.pk),
        actor=actor,
        on_behalf_of=True,
        reason="admin console",
    )


def _door_check_in(*, actor, booking):
    check_in(booking_id=BookingId(booking.pk), actor=actor)


def _door_no_show(*, actor, booking):
    mark_no_show(booking_id=BookingId(booking.pk), actor=actor)


@admin.register(Booking, site=bookr_site)
class BookingAdmin(VenueScopedAdmin):
    venue_path = "session__offering__venue"
    list_display = ("member", "status", "created_at")
    list_filter = ("status",)
    date_hierarchy = "created_at"
    # Status and its fellow travelers move only through the booking
    # services: transition_booking guards the write, and the services add
    # the refund, record, promotion, and notice around it. The console
    # changes bookings through the actions below, never the form — and
    # add/delete stay off, so no hand-made booking can bypass the spend
    # and no deletion can skip the refund, record, and notice.
    readonly_fields = (
        "created_at",
        "status",
        "hold_expires_at",
        "checked_in_at",
        "credits_spent",
        "membership",
        "version",
    )
    actions = ("cancel_bookings", "check_in_bookings", "mark_no_show_bookings")

    @admin.action(description="Cancel (staff on behalf, normal rules)")
    def cancel_bookings(self, request, queryset):
        self._apply(request, queryset, "Cancelled", _staff_cancel)

    @admin.action(description="Check in (door)")
    def check_in_bookings(self, request, queryset):
        self._apply(request, queryset, "Checked in", _door_check_in)

    @admin.action(description="Mark no-show (door)")
    def mark_no_show_bookings(self, request, queryset):
        self._apply(request, queryset, "Marked no-show", _door_no_show)

    def has_add_permission(self, request):
        # Hand-made bookings bypass the spend: create only via services.
        return False

    def has_delete_permission(self, request, obj=None):
        # Deletion skips the refund, record, and notice: cancel instead.
        return False

    def _apply(self, request, queryset, verb, func):
        applied, skipped = 0, 0
        for booking in queryset.iterator():
            try:
                func(actor=request.user, booking=booking)
            except BookingError, PermissionDenied, DjangoValidationError:
                skipped += 1
            else:
                applied += 1
        self.message_user(
            request,
            f"{verb}: {applied} applied, {skipped} skipped.",
            messages.SUCCESS if skipped == 0 else messages.WARNING,
        )


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
