from django.urls import path

from booking.views import (
    BookingCancelView,
    BookingsView,
    CheckInView,
    MineView,
    NoShowView,
    PolicyListView,
    RecordWaiveView,
    RosterView,
)

urlpatterns = [
    path("bookings/", BookingsView.as_view(), name="bookings"),
    path("bookings/me/", MineView.as_view(), name="booking-mine"),
    path("bookings/roster/", RosterView.as_view(), name="booking-roster"),
    path(
        "bookings/<int:pk>/cancel/",
        BookingCancelView.as_view(),
        name="booking-cancel",
    ),
    path(
        "bookings/<int:pk>/no-show/",
        NoShowView.as_view(),
        name="booking-no-show",
    ),
    path(
        "bookings/<int:pk>/check-in/",
        CheckInView.as_view(),
        name="booking-check-in",
    ),
    path("policies/", PolicyListView.as_view(), name="policies"),
    path(
        "records/<int:pk>/waive/",
        RecordWaiveView.as_view(),
        name="record-waive",
    ),
]
