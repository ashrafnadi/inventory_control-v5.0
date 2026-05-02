from django.db import migrations, models
import django.db.models.deletion


def ensure_faculty_item_stock_table(apps, schema_editor):
    FacultyItemStock = apps.get_model("inventory", "FacultyItemStock")
    existing_tables = schema_editor.connection.introspection.table_names()
    if FacultyItemStock._meta.db_table not in existing_tables:
        schema_editor.create_model(FacultyItemStock)


def populate_faculty_item_stocks(apps, schema_editor):
    FacultyItemStock = apps.get_model("inventory", "FacultyItemStock")
    ItemTransactions = apps.get_model("inventory", "ItemTransactions")

    for stock in FacultyItemStock.objects.filter(faculty__isnull=True).select_related(
        "item"
    ):
        txn = (
            ItemTransactions.objects.filter(
                itemtransactiondetails__item_id=stock.item_id,
            )
            .exclude(faculty__isnull=True)
            .order_by("created_at")
            .first()
        )
        if txn and txn.faculty_id:
            stock.faculty_id = txn.faculty_id
            stock.save(update_fields=["faculty"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0017_populate_transaction_faculty"),
    ]

    operations = [
        migrations.RunPython(
            ensure_faculty_item_stock_table, migrations.RunPython.noop
        ),
        migrations.AddField(
            model_name="facultyitemstock",
            name="faculty",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="item_stocks",
                to="administration.faculty",
                verbose_name="الكلية",
            ),
        ),
        migrations.RunPython(populate_faculty_item_stocks, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="facultyitemstock",
            name="faculty",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="item_stocks",
                to="administration.faculty",
                verbose_name="الكلية",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="facultyitemstock",
            unique_together={("faculty", "item", "sub_warehouse")},
        ),
    ]
