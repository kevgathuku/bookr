"""ID newtypes for service boundaries.

Org, venue, user, session, and booking PKs are all bare ints, so a
transposed call runs fine and corrupts silently — the types make mypy
catch the swap instead. Zero runtime cost (NewType is identity).
Typing-only module: no Django imports, so any app can use these
without cycle risk. Lives in common (not organizations) because every
app imports it — the reverse dependency would be a lie.
"""

from typing import NewType

OrgId = NewType("OrgId", int)
VenueId = NewType("VenueId", int)
UserId = NewType("UserId", int)
SessionId = NewType("SessionId", int)
BookingId = NewType("BookingId", int)
