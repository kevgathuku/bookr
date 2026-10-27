from django.urls import path

from booking.views import BookingsView, CancelView, MineView, NoShowView

urlpatterns = [
    path("bookings/", BookingsView.as_view(), name="bookings"),
    path("bookings/me/", MineView.as_view(), name="booking-mine"),
    path("bookings/<int:pk>/cancel/", CancelView.as_view(), name="booking-cancel"),
    path("bookings/<int:pk>/no-show/", NoShowView.as_view(), name="booking-no-show"),
]
