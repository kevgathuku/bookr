import pytest

from tests.factories import VenueFactory


@pytest.fixture
def venue():
    """A fresh venue (and organization). For tests needing any venue;
    tests needing a specific slug or a second venue call make_venue()."""
    return VenueFactory()
