from django.urls import path

from access.events import RecentEventsView
from access.views import CheckView

urlpatterns = [
    path("api/access/check/", CheckView.as_view(), name="access-check"),
    path("api/v1/access/events/", RecentEventsView.as_view(), name="access-events"),
]
