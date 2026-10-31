"""Scoped rule resolution: most-specific-wins, priority tiebreaks.

The org-wide NONE baseline always matches, so resolution never comes
back empty: uncovered contexts cancel free by design.
"""

from booking.models import CancellationPolicy

BASELINE_PRIORITY = -1


def resolve_policy(organization_id, venue_id, class_category, plan_type):
    """Return the winning rule for a booking context."""
    _ensure_baseline(organization_id)
    candidates = CancellationPolicy.objects.filter(organization_id=organization_id)
    matching = [
        policy
        for policy in candidates
        if _matches(policy, venue_id, class_category, plan_type)
    ]
    return max(matching, key=lambda policy: (policy.specificity, policy.priority))


def _ensure_baseline(organization_id):
    # Priority is part of the lookup: an org-wide explicit rule shares the
    # baseline's null scopes but never its priority, so the two coexist.
    CancellationPolicy.objects.get_or_create(
        organization_id=organization_id,
        venue=None,
        class_category=None,
        plan_type=None,
        priority=BASELINE_PRIORITY,
        defaults={
            "late_cancel_hours": 0,
            "enforcement": CancellationPolicy.Enforcement.NONE,
        },
    )


def _matches(policy, venue_id, class_category, plan_type):
    return (
        (policy.venue_id is None or policy.venue_id == venue_id)
        and (policy.class_category is None or policy.class_category == class_category)
        and (policy.plan_type is None or policy.plan_type == plan_type)
    )
