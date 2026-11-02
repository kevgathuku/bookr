"""Organization- and venue-ID newtypes for service boundaries.

Org and venue PKs are both bare ints, so a transposed call runs fine and
corrupts silently — the types make mypy catch the swap instead. Zero
runtime cost (NewType is identity). Typing-only module: no Django
imports, so any app can use these without cycle risk.
"""

from typing import NewType

OrgId = NewType("OrgId", int)
VenueId = NewType("VenueId", int)
