# Ends all open-ended memberships: every membership has a known window.
# Dev phase data only; seeds recreate rows going forward.
from datetime import timedelta

from django.db import migrations, models


def close_open_memberships(apps, schema_editor):
    Membership = apps.get_model("passes", "Membership")
    for membership in Membership.objects.filter(ends_on__isnull=True).select_related(
        "plan"
    ):
        membership.ends_on = membership.starts_on + timedelta(
            days=membership.plan.validity_days
        )
        membership.save(update_fields=["ends_on"])


class Migration(migrations.Migration):
    dependencies = [
        ("passes", "0003_plan_memberships"),
    ]

    operations = [
        migrations.RunPython(close_open_memberships, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="membership",
            name="ends_on",
            field=models.DateField(),
        ),
    ]
