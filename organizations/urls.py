from django.urls import path

from organizations.views import PolicyActivateView, PolicyListView

urlpatterns = [
    path("policies/", PolicyListView.as_view(), name="policy-list"),
    path("policies/activate/", PolicyActivateView.as_view(), name="policy-activate"),
]
