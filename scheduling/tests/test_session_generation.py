"""Session scheduling on the new graph (bookr-0sr.7 keeps this file lean)."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from scheduling.sessions import generate_sessions
from tests.factories import ClassOfferingFactory, ClassSessionFactory, VenueFactory

pytestmark = pytest.mark.django_db


class TestGenerateSessions:
    def _offering(self, venue):
        return ClassOfferingFactory(venue=venue, duration=timedelta(minutes=60))

    def test_weekly_rule_expands_in_window(self):
        venue = VenueFactory(slug="gen")
        offering = self._offering(venue)
        start = timezone.now() + timedelta(days=1)
        rule = start.strftime("DTSTART:%Y%m%dT%H%M%S\nRRULE:FREQ=WEEKLY;COUNT=3")

        sessions = generate_sessions(
            offering=offering,
            rrule=rule,
            after=start - timedelta(hours=1),
            before=start + timedelta(days=30),
        )

        assert len(sessions) == 3
        assert sessions[1].starts_at - sessions[0].starts_at == timedelta(weeks=1)

    def test_out_of_window_occurrences_skipped(self):
        venue = VenueFactory(slug="gen-skip")
        offering = self._offering(venue)
        start = timezone.now() + timedelta(days=1)
        rule = start.strftime("DTSTART:%Y%m%dT%H%M%S\nRRULE:FREQ=DAILY;COUNT=5")

        sessions = generate_sessions(
            offering=offering,
            rrule=rule,
            after=start + timedelta(days=1, hours=1),
            before=start + timedelta(days=30),
        )

        # Occurrences on days 3-5; days 1-2 fall before the window.
        assert len(sessions) == 3

    def test_clash_aborts_the_whole_batch(self):
        venue = VenueFactory(slug="gen-clash")
        offering = self._offering(venue)
        start = timezone.now() + timedelta(days=1)
        ClassSessionFactory(offering=offering, starts_at=start)
        rule = start.strftime("DTSTART:%Y%m%dT%H%M%S\nRRULE:FREQ=WEEKLY;COUNT=2")

        with pytest.raises(ValidationError):
            generate_sessions(
                offering=offering,
                rrule=rule,
                after=start - timedelta(hours=1),
                before=start + timedelta(days=30),
            )

        assert offering.sessions.count() == 1

    def test_garbage_rule_rejected(self):
        venue = VenueFactory(slug="gen-bad")
        offering = self._offering(venue)

        with pytest.raises(ValidationError):
            generate_sessions(
                offering=offering,
                rrule="not a rule",
                after=timezone.now(),
                before=timezone.now() + timedelta(days=30),
            )
