# Dev phase: old rows reference retired tables; dispose them before the
# schema changes (deferred FK checks would otherwise block the ALTERs).
from django.db import migrations


def dispose_bookings(apps, schema_editor):
    apps.get_model("booking", "Booking").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0005_cancellation_policy"),
    ]

    operations = [
        migrations.RunPython(dispose_bookings, migrations.RunPython.noop),
    ]
