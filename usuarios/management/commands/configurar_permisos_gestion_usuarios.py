from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Concede al grupo Administración únicamente el permiso de consultar "
        "el listado y detalle de cuentas de usuario."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        grupo = Group.objects.filter(name="Administración").first()
        if grupo is None:
            raise CommandError(
                "No existe el grupo Administración. Ejecuta primero "
                "configurar_institucional."
            )

        permiso = Permission.objects.filter(
            content_type__app_label="usuarios",
            content_type__model="usuario",
            codename="view_usuario",
        ).first()
        if permiso is None:
            raise CommandError(
                "No existe view_usuario. Ejecuta primero las migraciones "
                "con python manage.py migrate."
            )

        # add() conserva los permisos que el grupo ya tiene.
        grupo.permissions.add(permiso)
        self.stdout.write(
            self.style.SUCCESS(
                "Permiso view_usuario asignado a Administración. "
                "No se modificaron cuentas ni otros permisos."
            )
        )
