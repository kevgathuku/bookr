from django.urls import path

from passes.views import LedgerAdjustView, LedgerView, MembershipListView

urlpatterns = [
    path("ledger/", LedgerView.as_view(), name="ledger"),
    path("ledger/adjust/", LedgerAdjustView.as_view(), name="ledger-adjust"),
    path("memberships/", MembershipListView.as_view(), name="memberships"),
]
