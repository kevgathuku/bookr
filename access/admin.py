from django.contrib import admin, messages

from access.models import AccessEvent, AccessPoint
from organizations.admin_mixins import ReadOnlyAdmin, VenueScopedAdmin, bookr_site


@admin.register(AccessPoint, site=bookr_site)
class AccessPointAdmin(VenueScopedAdmin):
    list_display = ("name", "venue", "controller_id")
    list_filter = ("venue",)
    readonly_fields = ("api_token_hash",)
    actions = ("rotate_token",)

    @admin.action(description="Rotate controller token (plaintext shown once)")
    def rotate_token(self, request, queryset):
        for point in queryset:
            plaintext = point.set_token()
            point.save()
            self.message_user(
                request,
                f"{point}: new token {plaintext}",
                level=messages.WARNING,
            )


@admin.register(AccessEvent, site=bookr_site)
class AccessEventAdmin(ReadOnlyAdmin):
    venue_path = "access_point__venue"
    list_display = ("access_point", "member", "granted", "reason", "occurred_at")
    list_filter = ("granted", "reason")
    date_hierarchy = "occurred_at"
