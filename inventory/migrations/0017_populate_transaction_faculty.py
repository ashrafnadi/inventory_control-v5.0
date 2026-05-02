# inventory/migrations/0017_populate_transaction_faculty.py
from django.db import migrations


def populate_faculty(apps, schema_editor):
    ItemTransactions = apps.get_model("inventory", "ItemTransactions")
    for txn in ItemTransactions.objects.select_related(
        "created_by__profile__faculty"
    ).all():
        if (
            txn.created_by
            and hasattr(txn.created_by, "profile")
            and txn.created_by.profile.faculty
        ):
            txn.faculty = txn.created_by.profile.faculty
            txn.save(update_fields=["faculty"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0016_alter_item_options_alter_itemcategory_options_and_more")
    ]
    operations = [migrations.RunPython(populate_faculty, migrations.RunPython.noop)]
