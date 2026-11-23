"""Drop scope/priority/baseline columns; tier becomes the whole identity."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0011_policy_tier_seed"),
    ]

    operations = [
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
