"""
Carga las categorias del club y sus reglas de edad para una temporada.

Uso:
    python manage.py cargar_categorias
    python manage.py cargar_categorias --temporada 2027

El comando es idempotente: se puede volver a ejecutar sin duplicar filas.

IMPORTANTE: los tramos de edad de abajo se dedujeron del informe
(categorias mixtas hasta U11; U13, U15 y U17 divididas en damas y
varones; mas la categoria todo competidor para adultos). Antes de
usarlos como definitivos hay que confirmarlos con la contraparte,
sobre todo si "todo competidor" se divide por rama o es una sola.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from usuarios.models import Categoria, ReglaCategoria

# (nombre, rama, orden, edad_min, edad_max)
CATEGORIAS = [
    ("U7 Mixto", Categoria.Rama.MIXTO, 1, 6, 7),
    ("U9 Mixto", Categoria.Rama.MIXTO, 2, 8, 9),
    ("U11 Mixto", Categoria.Rama.MIXTO, 3, 10, 11),

    ("U13 Damas", Categoria.Rama.DAMAS, 4, 12, 13),
    ("U13 Varones", Categoria.Rama.VARONES, 5, 12, 13),

    ("U15 Damas", Categoria.Rama.DAMAS, 6, 14, 15),
    ("U15 Varones", Categoria.Rama.VARONES, 7, 14, 15),

    ("U17 Damas", Categoria.Rama.DAMAS, 8, 16, 17),
    ("U17 Varones", Categoria.Rama.VARONES, 9, 16, 17),

    ("T/C Damas", Categoria.Rama.DAMAS, 10, 18, None),
    ("T/C Varones", Categoria.Rama.VARONES, 11, 18, None),
]


class Command(BaseCommand):
    help = "Crea las categorias del club y sus reglas de edad."

    def add_arguments(self, parser):
        parser.add_argument(
            "--temporada",
            type=int,
            default=None,
            help="Anio de la temporada. Por defecto, el anio actual.",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        from django.utils import timezone

        temporada = opciones["temporada"] or timezone.localdate().year

        creadas = 0
        actualizadas = 0

        for nombre, rama, orden, edad_min, edad_max in CATEGORIAS:
            categoria, nueva = Categoria.objects.update_or_create(
                nombre=nombre,
                defaults={
                    "rama": rama,
                    "orden": orden,
                    "activa": True,
                },
            )

            _, regla_nueva = ReglaCategoria.objects.update_or_create(
                categoria=categoria,
                temporada=temporada,
                defaults={
                    "edad_min": edad_min,
                    "edad_max": edad_max,
                    "activa": True,
                },
            )

            if nueva or regla_nueva:
                creadas += 1
            else:
                actualizadas += 1

        if opciones.get("verbosity", 1):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Temporada {temporada}: {creadas} categorias creadas, "
                    f"{actualizadas} ya existian y quedaron actualizadas."
                )
            )
