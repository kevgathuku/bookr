from django.urls import path
from rest_framework.routers import DefaultRouter

from passes.catalog import GrantView, PassProductViewSet
from passes.views import AdjustView, LedgerView, MemberPassesView, MyPassesView

router = DefaultRouter()
router.register("pass-products", PassProductViewSet, basename="passproduct")

urlpatterns = [
    path("me/passes/", MyPassesView.as_view(), name="my-passes"),
    path("passes/", MemberPassesView.as_view(), name="member-passes"),
    path("ledger/", LedgerView.as_view(), name="ledger"),
    path("ledger/adjust/", AdjustView.as_view(), name="ledger-adjust"),
    path("passes/grant/", GrantView.as_view(), name="pass-grant"),
    *router.urls,
]
