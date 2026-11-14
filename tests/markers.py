"""Shared pytest markers.

requires_postgres skips tests that depend on Postgres-only behavior
when the suite runs on another backend.
"""

import pytest
from django.db import connection

requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Needs Postgres row locking for threaded races.",
)
