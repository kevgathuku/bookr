# Rename PlanType.COMP ("comp") to COMPLIMENTARY: "comp" is jargon,
# the full word is self-documenting. Dev phase, but keep it correct anyway.
from django.db import migrations, models


def rename_comp(apps, schema_editor):
    Plan = apps.get_model("passes", "MembershipPlan")
    Plan.objects.filter(plan_type="comp").update(plan_type="complimentary")


def rename_back(apps, schema_editor):
    Plan = apps.get_model("passes", "MembershipPlan")
    Plan.objects.filter(plan_type="complimentary").update(plan_type="comp")


class Migration(migrations.Migration):
    dependencies = [
        ("passes", "0004_membership_ends_on_required"),
    ]

    operations = [
        migrations.RunPython(rename_comp, rename_back),
        migrations.AlterField(
            model_name="membershipplan",
            name="plan_type",
            field=models.CharField(
                choices=[
                    ("monthly", "Monthly"),
                    ("credit_pack", "Credit pack"),
                    ("drop_in", "Drop-in"),
                    ("complimentary", "Complimentary"),
                ],
                max_length=20,
            ),
        ),
    ]
