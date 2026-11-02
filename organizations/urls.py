from django.urls import path

from organizations.views import (
    MemberSearchView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetView,
)

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("members/search/", MemberSearchView.as_view(), name="member-search"),
    path("auth/password-reset/", PasswordResetView.as_view(), name="password-reset"),
    path(
        "auth/password-reset-confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]
