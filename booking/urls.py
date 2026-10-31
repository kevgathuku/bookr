from django.urls import path

from booking.views import BookingsView, MineView, RosterView

urlpatterns = [
    path("bookings/", BookingsView.as_view(), name="bookings"),
    path("bookings/me/", MineView.as_view(), name="booking-mine"),
    path("bookings/roster/", RosterView.as_view(), name="booking-roster"),
]
