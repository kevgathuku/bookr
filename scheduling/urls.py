from django.urls import path
from rest_framework.routers import DefaultRouter

from scheduling.calendar import CalendarView
from scheduling.views import ScheduledClassViewSet

router = DefaultRouter()
router.register("classes", ScheduledClassViewSet, basename="scheduledclass")

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="calendar"),
    *router.urls,
]
