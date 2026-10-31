from django.urls import path

from passes.views import LedgerView

urlpatterns = [
    path("ledger/", LedgerView.as_view(), name="ledger"),
]
