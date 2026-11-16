"""Tier rule resolution: one row per tier per organization.

The trio is auto-created on first use with owner-confirmed seeds (trial
2h free, regular 12h lose-credit, monthly 0h free), so resolution never
comes back empty for house bookings. Aggregator (tierless) bookings sit
outside house policy: the partner contract governs, so they resolve to a
transient free policy that is never stored.
"""

from typing import cast

from booking.models import CancellationPolicy
from common.ids import OrgId
from passes.models import PlanTier

# Owner-confirmed seeds: trial is a short window with no penalty (trial
# seats turn over to waitlists), regular forfeits the credit, monthly
# carries no consequence (the subscription already priced the class).
SEEDS: tuple[tuple[str, int, str], ...] = (
    (PlanTier.TRIAL, 2, CancellationPolicy.Enforcement.NONE),
    (PlanTier.REGULAR, 12, CancellationPolicy.Enforcement.LOSE_CREDIT),
    (PlanTier.MONTHLY, 0, CancellationPolicy.Enforcement.NONE),
)


def ensure_tier_policies(organization_id: OrgId) -> None:
    """Create the three tier rows for an org. Idempotent and race-safe:
    the (organization, tier) unique admits exactly one row per tier."""
    for tier, window, enforcement in SEEDS:
        CancellationPolicy.objects.get_or_create(
            organization_id=organization_id,
            tier=tier,
            defaults={
                "late_cancel_hours": window,
                "enforcement": enforcement,
            },
        )


def resolve_policy(
    organization_id: OrgId,
    tier: str | None,
) -> CancellationPolicy:
    """Return the organization's row for a plan tier, or a transient free
    policy for tierless (aggregator) bookings."""
    ensure_tier_policies(organization_id)
    if tier is None:
        # Transient free policy: never stored, so the NULL tier the
        # column forbids is honest here (serializes as null). The cast
        # keeps the constructor's non-null contract for saved rows.
        return CancellationPolicy(
            organization_id=organization_id,
            tier=cast(str, tier),
            late_cancel_hours=0,
            enforcement=CancellationPolicy.Enforcement.NONE,
        )
    return CancellationPolicy.objects.get(organization_id=organization_id, tier=tier)
