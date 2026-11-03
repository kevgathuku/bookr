"""Entitlement x Validity axes (bookr-4ig/c61) + STAFF type.

Fresh-table migration: adds non-nullable columns without defaults, so it
applies cleanly to empty tables only. That is intentional — the project
is undeployed, local data is recreated via rewritten seeds, and any
placeholder default here would be fiction (credit counts vary per
purchase). Dev databases with seed rows: reset and re-seed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("passes", "0003_rehome_aggregator_vehicle"),
    ]

    operations = [
        # validity_days was always the period length; duration_days keeps
        # the values under the new name.
        migrations.RenameField(
            model_name="plan",
            old_name="validity_days",
            new_name="duration_days",
        ),
        migrations.AlterField(
            model_name="plan",
            name="duration_days",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="plan",
            name="entitlement",
            field=models.CharField(
                choices=[("unlimited", "Unlimited"), ("credits", "Credits")],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="credits_included",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="plan",
            name="validity",
            field=models.CharField(
                choices=[
                    ("open_ended", "Open-ended"),
                    ("fixed_duration", "Fixed duration"),
                    ("recurring", "Recurring"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="plan",
            name="plan_type",
            field=models.CharField(
                choices=[
                    ("monthly", "Monthly"),
                    ("credit_pack", "Credit pack"),
                    ("drop_in", "Drop-in"),
                    ("complimentary", "Complimentary"),
                    ("aggregator", "Aggregator"),
                    ("staff", "Staff"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="plan",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    entitlement="unlimited",
                    credits_included__isnull=True,
                )
                | models.Q(
                    entitlement="credits",
                    credits_included__isnull=False,
                    credits_included__gt=0,
                ),
                name="plan_credits_match_entitlement",
            ),
        ),
        migrations.AddConstraint(
            model_name="plan",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    validity="open_ended",
                    duration_days__isnull=True,
                )
                | models.Q(
                    validity__in=["fixed_duration", "recurring"],
                    duration_days__isnull=False,
                    duration_days__gt=0,
                ),
                name="plan_duration_match_validity",
            ),
        ),
        migrations.RenameField(
            model_name="membership",
            old_name="ends_on",
            new_name="valid_until",
        ),
        migrations.AlterField(
            model_name="membership",
            name="valid_until",
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="membership",
            name="credits_remaining",
            field=models.PositiveIntegerField(null=True, blank=True, default=0),
        ),
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True)
                | models.Q(valid_until__gte=models.F("starts_on")),
                name="membership_dates_ordered",
            ),
        ),
    ]
