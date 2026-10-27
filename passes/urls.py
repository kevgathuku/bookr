from django.urls import path

from passes.views import AdjustView, LedgerView, MyPassesView

urlpatterns = [
    path("me/passes/", MyPassesView.as_view(), name="my-passes"),
    path("ledger/", LedgerView.as_view(), name="ledger"),
    path("ledger/adjust/", AdjustView.as_view(), name="ledger-adjust"),
]
