from rest_framework.routers import DefaultRouter

from scheduling.views import ScheduledClassViewSet

router = DefaultRouter()
router.register("classes", ScheduledClassViewSet, basename="scheduledclass")

urlpatterns = router.urls
