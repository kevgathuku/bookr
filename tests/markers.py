"""Shared pytest markers.

requires_shared_db skips threaded race tests off Postgres. Threads need
one database shared across connections: the project's SQLite mode is
:memory: (per-connection, so threads race nothing), and file-backed
SQLite additionally needs busy-hardening this stack does not have yet
(probed: SQLITE_LOCKED in policy-ensure and membership reads) — that
is tracked separately, not gated here.
"""

import pytest
from django.db import connection

requires_shared_db = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Threaded races need one database shared across threads.",
)
