"""Shared pytest markers."""

import pytest
from django.db import connection

race_requires_postgres = pytest.mark.skipif(
    connection.vendor == "sqlite",
    reason="Threaded writer races need Postgres row locking; "
    "sqlite serializes writers.",
)
