from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0004_alter_department_options_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="faculty",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="administration.faculty",
                verbose_name="الكلية",
            ),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="administration.department",
                verbose_name="القسم",
            ),
        ),
    ]
