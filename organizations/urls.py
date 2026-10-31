from django.urls import path

from organizations.views import MemberSearchView, MeView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("members/search/", MemberSearchView.as_view(), name="member-search"),
]
