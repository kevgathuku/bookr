from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("passes", "0006_creditledger_cancellation_record_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="MembershipPlan",
            new_name="Plan",
        ),
    ]
