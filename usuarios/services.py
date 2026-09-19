from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import Categoria, ReglaCategoria


def calcular_edad(fecha_nacimiento, fecha_referencia=None):
    if fecha_referencia is None:
        fecha_referencia = timezone.localdate()

    if fecha_nacimiento > fecha_referencia:
        raise ValidationError(
            "La fecha de nacimiento no puede estar en el futuro."
        )

    return (
        fecha_referencia.year
        - fecha_nacimiento.year
        - (
            (fecha_referencia.month, fecha_referencia.day)
            <
            (
                fecha_nacimiento.month,
                fecha_nacimiento.day,
            )
        )
    )


def obtener_categoria_automatica(
    fecha_nacimiento,
    rama,
    temporada=None,
    fecha_referencia=None,
):
    if fecha_referencia is None:
        fecha_referencia = timezone.localdate()

    if temporada is None:
        temporada = fecha_referencia.year

    if rama not in (
        Categoria.Rama.DAMAS,
        Categoria.Rama.VARONES,
    ):
        raise ValidationError(
            "La rama del jugador debe ser DAMAS o VARONES."
        )

    edad = calcular_edad(
        fecha_nacimiento,
        fecha_referencia,
    )

    reglas = (
        ReglaCategoria.objects
        .select_related("categoria")
        .filter(
            temporada=temporada,
            activa=True,
            categoria__activa=True,
            edad_min__lte=edad,
        )
        .filter(
            Q(edad_max__isnull=True)
            | Q(edad_max__gte=edad)
        )
        .filter(
            Q(categoria__rama=Categoria.Rama.MIXTO)
            | Q(categoria__rama=rama)
        )
    )

    cantidad = reglas.count()

    if cantidad == 0:
        return None

    if cantidad > 1:
        raise ValidationError(
            "Existe más de una regla de categoría aplicable. "
            "Revise la configuración."
        )

    return reglas.first().categoria