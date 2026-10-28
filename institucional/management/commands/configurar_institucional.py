from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Configura grupos institucionales sin asignar cuentas ni reemplazar permisos existentes."

    @transaction.atomic
    def handle(self, *args, **options):
        configuracion = {
            "Administración": ["view_documentonormativo", "add_documentonormativo", "change_documentonormativo", "publicar_documentonormativo", "gestionar_miembros"],
            "Secretaría": ["view_acta", "add_acta", "change_acta", "publicar_acta"],
            "Comité de Disciplina": ["view_sancion", "add_sancion", "change_sancion", "resolver_sancion"],
            "Miembros autorizados": ["consultar_documentos_institucionales"],
        }
        for nombre, codigos in configuracion.items():
            grupo, _ = Group.objects.get_or_create(name=nombre)
            permisos = Permission.objects.filter(content_type__app_label="institucional", codename__in=codigos)
            if permisos.count() != len(codigos):
                raise CommandError("Primero aplica las migraciones de Institucional.")
            grupo.permissions.add(*permisos)
        self.stdout.write(self.style.SUCCESS("Grupos configurados. No se asignaron usuarios."))
