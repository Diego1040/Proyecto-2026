from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from finanzas.models import Cuota, Pago


class Command(BaseCommand):
    help = "Configura el grupo de permisos de Tesorería."

    def handle(self, *args, **options):
        grupo, _ = Group.objects.get_or_create(
            name="Tesorería"
        )

        for modelo in (Cuota, Pago):
            content_type = ContentType.objects.get_for_model(
                modelo
            )

            permisos = Permission.objects.filter(
                content_type=content_type,
                codename__in=[
                    f"view_{modelo._meta.model_name}",
                    f"add_{modelo._meta.model_name}",
                    f"change_{modelo._meta.model_name}",
                ],
            )

            grupo.permissions.add(*permisos)

        self.stdout.write(
            self.style.SUCCESS(
                "El grupo Tesorería está configurado correctamente."
            )
        )