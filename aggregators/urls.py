from django.urls import path

from aggregators.staff import (
    StaffAggregatorDetailView,
    StaffAggregatorEventsView,
    StaffAggregatorListView,
    StaffAggregatorRotateView,
)
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
    path(
        "staff/aggregators/",
        StaffAggregatorListView.as_view(),
        name="staff-aggregators",
    ),
    path(
        "staff/aggregators/<slug:slug>/",
        StaffAggregatorDetailView.as_view(),
        name="staff-aggregator",
    ),
    path(
        "staff/aggregators/<slug:slug>/rotate/",
        StaffAggregatorRotateView.as_view(),
        name="staff-aggregator-rotate",
    ),
    path(
        "staff/aggregators/<slug:slug>/events/",
        StaffAggregatorEventsView.as_view(),
        name="staff-aggregator-events",
    ),
]
