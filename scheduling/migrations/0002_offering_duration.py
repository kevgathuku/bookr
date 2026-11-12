"""Replace duration_minutes (int) with duration (DurationField).

New field + backfill rather than AlterField: Postgres cannot cast int to
interval implicitly, so an in-place alter would need a hand-written USING
clause per backend. Adding the column nullable, copying minutes over in
Python, then tightening to the default keeps one migration working on
both Postgres and sqlite.
"""

from datetime import timedelta

from django.core.validators import MinValueValidator
from django.db import migrations, models


def backfill_duration(apps, schema_editor):
    ClassOffering = apps.get_model("scheduling", "ClassOffering")
    for offering in ClassOffering.objects.all().iterator():
        offering.duration = timedelta(minutes=offering.duration_minutes)
        offering.save(update_fields=["duration"])


def unfill_duration(apps, schema_editor):
    ClassOffering = apps.get_model("scheduling", "ClassOffering")
    for offering in ClassOffering.objects.all().iterator():
        total_minutes = offering.duration // timedelta(minutes=1)
        offering.duration_minutes = total_minutes
        offering.save(update_fields=["duration_minutes"])


class Migration(migrations.Migration):

    dependencies = [
        ("scheduling", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="classoffering",
            name="duration",
            field=models.DurationField(null=True),
        ),
        migrations.RunPython(backfill_duration, unfill_duration),
        migrations.AlterField(
            model_name="classoffering",
            name="duration",
            field=models.DurationField(
                default=timedelta(minutes=60),
                validators=[MinValueValidator(timedelta(0))],
            ),
        ),
        migrations.RemoveField(
            model_name="classoffering",
            name="duration_minutes",
        ),
        migrations.AddConstraint(
            model_name="classoffering",
            constraint=models.CheckConstraint(
                condition=models.Q(duration__gte=timedelta(0)),
                name="offering_duration_nonnegative",
            ),
        ),
    ]
