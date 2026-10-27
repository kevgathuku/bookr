from django.urls import path

from organizations.views import (
    CurrentPolicyView,
    MeView,
    PolicyActivateView,
    PolicyListView,
)

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("policy/", CurrentPolicyView.as_view(), name="policy-current"),
    path("policies/", PolicyListView.as_view(), name="policy-list"),
    path("policies/activate/", PolicyActivateView.as_view(), name="policy-activate"),
]
