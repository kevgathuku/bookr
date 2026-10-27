from django.urls import path

from booking.views import (
    BookingsView,
    CancelView,
    CheckinView,
    MineView,
    NoShowView,
    RosterView,
)

urlpatterns = [
    path("bookings/", BookingsView.as_view(), name="bookings"),
    path("bookings/me/", MineView.as_view(), name="booking-mine"),
    path("bookings/roster/", RosterView.as_view(), name="booking-roster"),
    path("bookings/<int:pk>/cancel/", CancelView.as_view(), name="booking-cancel"),
    path("bookings/<int:pk>/no-show/", NoShowView.as_view(), name="booking-no-show"),
    path("bookings/<int:pk>/checkin/", CheckinView.as_view(), name="booking-checkin"),
]
