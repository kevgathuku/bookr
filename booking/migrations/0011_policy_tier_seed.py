"""Add the tier column alongside the scope columns; seed the trio; audit."""

from django.db import migrations, models

# Owner-confirmed seeds: (tier, late_cancel_hours, enforcement).
SEEDS = (
    ("trial", 2, "none"),
    ("regular", 12, "lose_credit"),
    ("monthly", 0, "none"),
)

# plan_type -> tier for pure plan-type-scoped rows. Aggregator is tierless
# by design; venue/category-scoped rows have no clear tier.
TIER_BY_PLAN_TYPE = {
    "complimentary": "trial",
    "staff": "trial",
    "credit_pack": "regular",
    "drop_in": "regular",
    "monthly": "monthly",
}


def seed_and_audit(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    CancellationPolicy = apps.get_model("booking", "CancellationPolicy")
    for org in Organization.objects.all():
        for tier, window, enforcement in SEEDS:
            CancellationPolicy.objects.get_or_create(
                organization=org,
                tier=tier,
                defaults={
                    "late_cancel_hours": window,
                    "enforcement": enforcement,
                },
            )
    quarantined = []
    for row in CancellationPolicy.objects.filter(tier__isnull=True):
        if row.venue_id is not None or row.class_category is not None:
            quarantined.append((row.pk, "venue/category-scoped; no clear tier"))
        elif row.plan_type is None:
            print(f"superseded baseline/org-wide row #{row.pk}: seeds win")
        elif row.plan_type == "aggregator":
            quarantined.append((row.pk, "aggregator plan; tierless by design"))
        else:
            print(
                f"adopted plan-type row #{row.pk}: "
                f"{row.plan_type} -> {TIER_BY_PLAN_TYPE[row.plan_type]} (seeds win)"
            )
    for pk, reason in quarantined:
        print(f"QUARANTINED scope row #{pk}: {reason}")
    if quarantined:
        print(f"quarantined rows: {[pk for pk, _ in quarantined]}")


def drop_legacy_rows(apps, schema_editor):
    CancellationPolicy = apps.get_model("booking", "CancellationPolicy")
    legacy = CancellationPolicy.objects.filter(tier__isnull=True)
    count = legacy.count()
    legacy.delete()
    print(f"dropped {count} legacy scope rows (audit above)")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0010_booking_held_requires_hold_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="cancellationpolicy",
            name="tier",
            field=models.CharField(
                blank=True,
                choices=[
                    ("trial", "Trial"),
                    ("regular", "Regular"),
                    ("monthly", "Monthly"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        # The old scope partials predate tier: the trio (three org-wide
        # rows per org) collides with them, so they go before the seed.
        # 0012 drops the columns and the choice CHECKs after purging.
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_all_set_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_no_venue_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_no_category_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_no_plan_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_venue_only_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_category_only_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_plan_only_unique",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="policy_scope_org_wide_unique",
        ),
        # The new unique goes before the seed: NULL tiers never collide,
        # and all DDL must precede the INSERTs — Postgres refuses ALTER
        # TABLE with pending trigger events in the same transaction.
        migrations.AddConstraint(
            model_name="cancellationpolicy",
            constraint=models.UniqueConstraint(
                fields=("organization", "tier"),
                name="policy_org_tier_unique",
            ),
        ),
        migrations.RunPython(seed_and_audit, noop),
        # Same-transaction DML only: the columns die in 0012, which stays
        # pure DDL, so no migration mixes row writes with schema changes.
        migrations.RunPython(drop_legacy_rows, noop),
    ]
