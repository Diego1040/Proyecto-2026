from django.contrib.auth.hashers import is_password_usable
from django.db import migrations
from django.utils import timezone


def reconocer_cuentas_existentes(apps, schema_editor):
    Usuario = apps.get_model("usuarios", "Usuario")
    Jugador = apps.get_model("usuarios", "Jugador")
    Apoderado = apps.get_model("usuarios", "Apoderado")
    alias = schema_editor.connection.alias
    fecha_reconocimiento = timezone.now()

    for usuario in Usuario.objects.using(alias).all().iterator():
        if usuario.is_active and is_password_usable(usuario.password):
            Usuario.objects.using(alias).filter(pk=usuario.pk).update(
                activado_en=fecha_reconocimiento,
            )
        if usuario.email:
            Jugador.objects.using(alias).filter(usuario_id=usuario.pk, email="").update(
                email=usuario.email,
            )
            Apoderado.objects.using(alias).filter(usuario_id=usuario.pk, email="").update(
                email=usuario.email,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0010_apoderado_email_jugador_email_and_more"),
    ]

    operations = [
        migrations.RunPython(reconocer_cuentas_existentes, migrations.RunPython.noop),
    ]
