from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def assign_open_year_to_transactions(apps, schema_editor):
    InventoryYear = apps.get_model("administration", "InventoryYear")
    ItemTransactions = apps.get_model("inventory", "ItemTransactions")

    open_year = InventoryYear.objects.filter(is_open=True).first()
    if open_year is None:
        open_year, _ = InventoryYear.objects.get_or_create(
            year=django.utils.timezone.now().year,
            defaults={"is_open": True, "opened_at": django.utils.timezone.now()},
        )
    ItemTransactions.objects.filter(year__isnull=True).update(year=open_year)


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0006_systemsettings_inventoryyear"),
        ("inventory", "0027_alter_item_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="itemtransactions",
            name="year",
            field=models.ForeignKey(
                blank=True,
                help_text="السنة المفتوحة وقت إنشاء السند.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="transactions",
                to="administration.inventoryyear",
                verbose_name="سنة المخزون",
            ),
        ),
        migrations.AddIndex(
            model_name="itemtransactions",
            index=models.Index(
                fields=["year", "created_at"],
                name="inventory_i_year_id_75455c_idx",
            ),
        ),
        migrations.RunPython(
            assign_open_year_to_transactions, migrations.RunPython.noop
        ),
    ]
