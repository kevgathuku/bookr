from django.urls import path
from rest_framework.routers import DefaultRouter

from scheduling.calendar import CalendarView
from scheduling.slots import AvailabilitySlotsView
from scheduling.views import (
    ClassTypeViewSet,
    RoomViewSet,
    ScheduledClassViewSet,
    TeacherSubstitutionViewSet,
)

router = DefaultRouter()
router.register("classes", ScheduledClassViewSet, basename="scheduledclass")
router.register("rooms", RoomViewSet, basename="room")
router.register("class-types", ClassTypeViewSet, basename="classtype")
router.register("substitutions", TeacherSubstitutionViewSet, basename="substitution")

urlpatterns = [
    path("calendar/", CalendarView.as_view(), name="calendar"),
    path("availability/slots/", AvailabilitySlotsView.as_view(), name="slots"),
    *router.urls,
]
