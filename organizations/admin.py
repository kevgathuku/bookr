"""Back-office admin: OrgRole rows are the single source of truth —
Django Groups are never consulted. Owner/manager get the full
back-office; frontdesk keeps view+change as a desk fallback; teacher/member
never enter, even with is_staff set or inside a Group."""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db.models import Q

from organizations.admin_mixins import VenueScopedAdmin, bookr_site, scoped_venues
from organizations.models import Organization, OrgRole, Venue

User = get_user_model()


@admin.register(Organization, site=bookr_site)
class OrganizationAdmin(VenueScopedAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")

    def scope_q(self, request):
        orgs = OrgRole.objects.filter(user=request.user).values("organization")
        return Q(pk__in=orgs)


@admin.register(Venue, site=bookr_site)
class VenueAdmin(VenueScopedAdmin):
    list_display = ("name", "organization", "slug")
    list_filter = ("organization",)
    search_fields = ("name", "slug")

    def scope_q(self, request):
        return Q(pk__in=scoped_venues(request))


def _clean_email(form):
    email = (form.cleaned_data.get("email") or "").strip()
    if not email:
        raise ValidationError(
            "Email is required: class and cancellation notices are sent there.",
        )
    return email


class BookrUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        return _clean_email(self)


class BookrUserChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "email", "is_active", "is_staff")

    def clean_email(self):
        return _clean_email(self)


@admin.register(User, site=bookr_site)
class BookrUserAdmin(VenueScopedAdmin):
    """Staff-provisioned members: email is mandatory, never invented later."""

    form = BookrUserChangeForm
    add_form = BookrUserCreationForm
    add_fieldsets = (
        (None, {"fields": ("username", "email", "password1", "password2")}),
    )
    list_display = ("username", "email", "is_active")
    search_fields = ("username", "email")

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return ((None, {"fields": ("username", "email", "is_active", "is_staff")}),)

    # Django ModelAdmin hook name (mirrors UserAdmin), not a home-grown getter.
    def get_form(self, request, obj=None, **kwargs):  # noqa: WPS615
        if obj is None:
            kwargs["form"] = self.add_form
        return super().get_form(request, obj, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).distinct()

    def scope_q(self, request):
        venues = scoped_venues(request)
        return Q(org_roles__venue__in=venues) | Q(
            org_roles__venue__isnull=True,
            org_roles__organization__in=venues.values("organization"),
        )


@admin.register(OrgRole, site=bookr_site)
class OrgRoleAdmin(VenueScopedAdmin):
    venue_path = "venue"
    list_display = ("user", "organization", "venue", "role")
    list_filter = ("organization", "role")
    search_fields = ("user__username",)

    def scope_q(self, request):
        venues = scoped_venues(request)
        return Q(venue__in=venues) | Q(
            venue__isnull=True,
            organization__in=venues.values("organization"),
        )
