from django.urls import path

from aggregators.views import (
    PartnerBookingsView,
    PartnerCancelView,
    PartnerScheduleView,
)

urlpatterns = [
    path(
        "aggregators/<slug:slug>/bookings/",
        PartnerBookingsView.as_view(),
        name="partner-bookings",
    ),
    path(
        "aggregators/<slug:slug>/bookings/<str:external_id>/cancel/",
        PartnerCancelView.as_view(),
        name="partner-cancel",
    ),
    path(
        "aggregators/<slug:slug>/schedule/",
        PartnerScheduleView.as_view(),
        name="partner-schedule",
    ),
]
