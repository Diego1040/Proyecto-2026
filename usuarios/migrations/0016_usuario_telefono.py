from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0015_periodoinactividad"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="telefono",
            field=models.CharField(
                blank=True,
                default="",
                max_length=20,
                verbose_name="Teléfono personal",
            ),
        ),
    ]
