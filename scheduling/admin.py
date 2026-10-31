from django.contrib import admin

from organizations.admin_mixins import VenueScopedAdmin, bookr_site
from scheduling import appointments_admin  # noqa: F401 — registers appointment admins
from scheduling.catalogue import ClassSession
from scheduling.models import ClassType, Room, ScheduledClass, TeacherSubstitution


@admin.register(ClassType, site=bookr_site)
class ClassTypeAdmin(VenueScopedAdmin):
    list_display = ("name", "venue", "duration_min")
    list_filter = ("venue",)
    search_fields = ("name",)


@admin.register(Room, site=bookr_site)
class RoomAdmin(VenueScopedAdmin):
    list_display = ("name", "venue", "capacity")
    list_filter = ("venue",)
    search_fields = ("name",)


@admin.register(ScheduledClass, site=bookr_site)
class ScheduledClassAdmin(VenueScopedAdmin):
    list_display = ("class_type", "venue", "starts_at", "status")
    list_filter = ("venue", "status")
    date_hierarchy = "starts_at"


@admin.register(TeacherSubstitution, site=bookr_site)
class TeacherSubstitutionAdmin(VenueScopedAdmin):
    venue_path = "scheduled_class__venue"
    list_display = ("scheduled_class", "old_teacher", "new_teacher")
    readonly_fields = ("old_teacher", "created_by")

    def save_model(self, request, obj, form, change):
        # History integrity: past teacher and recorder always derive from
        # the class roster and the logged-in user, never the form.
        obj.old_teacher = obj.scheduled_class.teacher
        obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        # Append-only history: view, never rewrite.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClassSession, site=bookr_site)
class ClassSessionAdmin(VenueScopedAdmin):
    venue_path = "offering__venue"
    list_display = ("offering", "starts_at", "capacity", "cancelled_at")
    list_filter = ("offering__category",)
    date_hierarchy = "starts_at"
