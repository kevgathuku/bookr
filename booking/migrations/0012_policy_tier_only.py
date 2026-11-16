"""Drop scope/priority/baseline columns; tier becomes the whole identity."""

from django.db import migrations, models


def drop_legacy_rows(apps, schema_editor):
    CancellationPolicy = apps.get_model("booking", "CancellationPolicy")
    legacy = CancellationPolicy.objects.filter(tier__isnull=True)
    count = legacy.count()
    legacy.delete()
    print(f"dropped {count} legacy scope rows (audit in 0011)")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0011_policy_tier_seed"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_rows, noop),
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
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="cancellationpolicy_class_category_valid",
        ),
        migrations.RemoveConstraint(
            model_name="cancellationpolicy",
            name="cancellationpolicy_plan_type_valid",
        ),
        migrations.RemoveField(
            model_name="cancellationpolicy",
            name="venue",
        ),
        migrations.RemoveField(
            model_name="cancellationpolicy",
            name="class_category",
        ),
        migrations.RemoveField(
            model_name="cancellationpolicy",
            name="plan_type",
        ),
        migrations.RemoveField(
            model_name="cancellationpolicy",
            name="priority",
        ),
        migrations.AlterField(
            model_name="cancellationpolicy",
            name="tier",
            field=models.CharField(
                choices=[("trial", "Trial"), ("regular", "Regular"), ("monthly", "Monthly")],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="cancellationpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(tier__in=["trial", "regular", "monthly"]),
                name="cancellationpolicy_tier_valid",
            ),
        ),
    ]
