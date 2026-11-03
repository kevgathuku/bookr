"""Re-home the partner vehicle under the AGGREGATOR plan type.

COMPLIMENTARY now means house-granted (goodwill, staff comps); the only
plans carrying it are the auto-created partner vehicles, renamed here.
Literals, not PlanType members: migrations freeze history and must not
import live code.
"""

from django.db import migrations


def rehome_vehicle(apps, _schema_editor):
    apps.get_model("passes", "Plan").objects.filter(
        name="Aggregator complimentary",
    ).update(plan_type="aggregator", name="Aggregator allotment")


def reverse_vehicle(apps, _schema_editor):
    apps.get_model("passes", "Plan").objects.filter(
        name="Aggregator allotment",
    ).update(plan_type="complimentary", name="Aggregator complimentary")


class Migration(migrations.Migration):

    dependencies = [
        ("passes", "0002_alter_plan_plan_type"),
    ]

    operations = [
        migrations.RunPython(rehome_vehicle, reverse_vehicle, elidable=True),
    ]
