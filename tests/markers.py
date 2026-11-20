"""Shared pytest markers.

requires_shared_db skips threaded race tests when the suite runs on a
backend without one database shared across threads (in-memory SQLite
gives each connection its own database, so threads race nothing).
"""

import pytest
from django.db import connection

requires_shared_db = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Threaded races need one database shared across threads.",
)
