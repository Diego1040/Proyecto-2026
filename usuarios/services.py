from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.db import transaction

from .models import (
    Categoria, 
    ReglaCategoria,
    HistorialCategoria,
    Jugador,
)


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

@transaction.atomic
def asignar_categoria_automatica(
    jugador,
    temporada=None,
    fecha_referencia=None,
):
    nueva_categoria = obtener_categoria_automatica(
        fecha_nacimiento=jugador.fecha_nacimiento,
        rama=jugador.rama,
        temporada=temporada,
        fecha_referencia=fecha_referencia,
    )

    if nueva_categoria is None:
        return None

    categoria_anterior = jugador.categoria_actual

    if categoria_anterior_id_igual(
        categoria_anterior,
        nueva_categoria,
    ):
        return nueva_categoria

    jugador.categoria_actual = nueva_categoria
    jugador.save(update_fields=["categoria_actual"])

    HistorialCategoria.objects.create(
        jugador=jugador,
        categoria_anterior=categoria_anterior,
        categoria_nueva=nueva_categoria,
        tipo_cambio=HistorialCategoria.TipoCambio.AUTOMATICO,
    )

    return nueva_categoria


def categoria_anterior_id_igual(anterior, nueva):
    if anterior is None:
        return False

    return anterior.pk == nueva.pk

@transaction.atomic
def cambiar_categoria_manual(
    jugador,
    nueva_categoria,
    usuario,
    motivo,
):
    if not motivo or not motivo.strip():
        raise ValidationError(
            "La excepcion manual requiere un motivo."
        )

    if usuario is None:
        raise ValidationError(
            "Debe indicar el usuario que realiza el cambio."
        )

    categoria_anterior = jugador.categoria_actual

    if (
        categoria_anterior
        and categoria_anterior.pk == nueva_categoria.pk
    ):
        raise ValidationError(
            "La nueva categoría debe ser distinta "
            "de la categoria actual."
        )

    jugador.categoria_actual = nueva_categoria
    jugador.save(update_fields=["categoria_actual"])

    historial = HistorialCategoria(
        jugador=jugador,
        categoria_anterior=categoria_anterior,
        categoria_nueva=nueva_categoria,
        tipo_cambio=(
            HistorialCategoria.TipoCambio.EXCEPCION_MANUAL
        ),
        motivo=motivo.strip(),
        cambiado_por=usuario,
    )

    historial.full_clean()
    historial.save()

    return nueva_categoria