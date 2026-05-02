from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def create_initial_settings_and_year(apps, schema_editor):
    SystemSettings = apps.get_model("administration", "SystemSettings")
    InventoryYear = apps.get_model("administration", "InventoryYear")

    SystemSettings.objects.get_or_create(pk=1)
    current_year = django.utils.timezone.now().year
    if not InventoryYear.objects.filter(is_open=True).exists():
        InventoryYear.objects.get_or_create(
            year=current_year,
            defaults={"is_open": True, "opened_at": django.utils.timezone.now()},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0005_userprofile_nullable_faculty_department"),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryYear",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("year", models.PositiveIntegerField(unique=True, verbose_name="السنة")),
                ("is_open", models.BooleanField(default=True, verbose_name="مفتوحة")),
                (
                    "opened_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="تاريخ الفتح"
                    ),
                ),
                (
                    "closed_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="تاريخ الإغلاق"
                    ),
                ),
            ],
            options={
                "verbose_name": "سنة المخزون",
                "verbose_name_plural": "سنوات المخزون",
                "ordering": ["-year"],
            },
        ),
        migrations.CreateModel(
            name="SystemSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "idle_timeout_minutes",
                    models.PositiveIntegerField(
                        default=30,
                        help_text="عدد الدقائق بدون نشاط قبل تسجيل الخروج التلقائي.",
                        verbose_name="مدة الخمول قبل تسجيل الخروج (دقيقة)",
                    ),
                ),
                (
                    "session_warning_minutes",
                    models.PositiveIntegerField(
                        default=5,
                        help_text="عدد الدقائق قبل انتهاء الجلسة لإظهار نافذة التحذير.",
                        verbose_name="التحذير قبل انتهاء الجلسة (دقيقة)",
                    ),
                ),
            ],
            options={
                "verbose_name": "إعدادات النظام",
                "verbose_name_plural": "إعدادات النظام",
            },
        ),
        migrations.AddConstraint(
            model_name="inventoryyear",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_open=True),
                fields=("is_open",),
                name="unique_open_inventory_year",
            ),
        ),
        migrations.RunPython(create_initial_settings_and_year, migrations.RunPython.noop),
    ]
