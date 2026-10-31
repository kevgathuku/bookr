from django.urls import path
from rest_framework.routers import DefaultRouter

from scheduling.calendar import CalendarView
from scheduling.views import OfferingViewSet, SessionViewSet

router = DefaultRouter()
router.register("offerings", OfferingViewSet, basename="offering")
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="calendar"),
    *router.urls,
]
