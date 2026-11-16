"""Plan tier: trial/regular/monthly per plan type, aggregator tierless."""

from django.db import migrations, models


def backfill_tier(apps, schema_editor):
    Plan = apps.get_model("passes", "Plan")
    mapping = {
        "complimentary": "trial",
        "staff": "trial",
        "credit_pack": "regular",
        "drop_in": "regular",
        "monthly": "monthly",
        # aggregator intentionally absent: tierless (NULL).
    }
    for plan_type, tier in mapping.items():
        Plan.objects.filter(plan_type=plan_type, tier__isnull=True).update(tier=tier)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("passes", "0007_creditledger_creditledger_reason_valid_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
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
        migrations.RunPython(backfill_tier, noop),
        migrations.AddConstraint(
            model_name="plan",
            constraint=models.CheckConstraint(
                condition=models.Q(plan_type="aggregator", tier__isnull=True)
                | (
                    models.Q(tier__isnull=False)
                    & models.Q(tier__in=["trial", "regular", "monthly"])
                    & ~models.Q(plan_type="aggregator")
                ),
                name="plan_tier_matches_plan_type",
            ),
        ),
    ]
