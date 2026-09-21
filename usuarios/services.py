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
    SolicitudInscripcion,
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

@transaction.atomic
def crear_solicitud_inscripcion(
    *,
    jugador,
    solicitante=None,
    consentimiento,
    observaciones="",
    temporada=None,
    fecha_referencia=None,
):
    """
    Crea una solicitud de inscripcion para un jugador

    - Valida al jugador.
    - Comprueba apoderado activo si es menor de edad
    - Asigna categoria automaticamente
    - Crea la solicitud en estado pendiente
    """

    if fecha_referencia is None:
        fecha_referencia = timezone.localdate()

    jugador.full_clean()

    # Permite utilizar tanto un jugador nuevo como uno ya guardado.
    if jugador.pk is None:
        jugador.save()

    edad = calcular_edad(
        jugador.fecha_nacimiento,
        fecha_referencia,
    )

    if edad < 18:
        tiene_apoderado = (
            jugador.vinculos_apoderados
            .filter(activo=True)
            .exists()
        )

        if not tiene_apoderado:
            raise ValidationError(
                "Un jugador menor de edad debe tener "
                "al menos un apoderado activo."
            )

    categoria = asignar_categoria_automatica(
        jugador=jugador,
        temporada=temporada,
        fecha_referencia=fecha_referencia,
    )

    if categoria is None:
        raise ValidationError(
            "No existe una categoría aplicable "
            "para el jugador."
        )

    solicitud = SolicitudInscripcion(
        jugador=jugador,
        solicitante=solicitante,
        procedencia=jugador.procedencia,
        club_anterior=jugador.club_anterior,
        observaciones=observaciones.strip(),
        consentimiento=consentimiento,
    )

    solicitud.full_clean()
    solicitud.save()

    return solicitud

@transaction.atomic
def marcar_solicitud_en_revision(*, solicitud):
    if solicitud.estado != SolicitudInscripcion.Estado.PENDIENTE:
        raise ValidationError(
            "Solo una solicitud pendiente puede pasar a revision."
        )

    solicitud.estado = SolicitudInscripcion.Estado.EN_REVISION
    solicitud.full_clean()
    solicitud.save(update_fields=["estado"])

    return solicitud

@transaction.atomic
def aprobar_solicitud_inscripcion(
    *,
    solicitud,
    usuario,
):
    if usuario is None:
        raise ValidationError(
            "Debe indicar el usuario que aprueba la solicitud."
        )

    if solicitud.estado != SolicitudInscripcion.Estado.EN_REVISION:
        raise ValidationError(
            "Solo una solicitud en revision puede ser aprobada."
        )

    jugador = solicitud.jugador

    if jugador.categoria_actual_id is None:
        raise ValidationError(
            "El jugador debe tener una categoria asignada "
            "antes de aprobar la solicitud."
        )

    solicitud.estado = SolicitudInscripcion.Estado.APROBADA
    solicitud.revisado_por = usuario
    solicitud.fecha_revision = timezone.now()
    solicitud.motivo_rechazo = ""

    solicitud.full_clean()
    solicitud.save()

    jugador.estado = Jugador.Estado.ACTIVO

    if jugador.fecha_ingreso is None:
        jugador.fecha_ingreso = timezone.localdate()

    jugador.full_clean()
    jugador.save()

    registrar_auditoria(
        usuario=usuario,
        accion="SOLICITUD_APROBADA",
        entidad="SolicitudInscripcion",
        entidad_id=solicitud.pk,
        detalle={
            "jugador_id": jugador.pk,
            "estado_anterior": "EN_REVISION",
            "estado_nuevo": "APROBADA",
        },
    )

    return solicitud

@transaction.atomic
def rechazar_solicitud_inscripcion(
    *,
    solicitud,
    usuario,
    motivo,
):
    if usuario is None:
        raise ValidationError(
            "Debe indicar el usuario que rechaza la solicitud."
        )

    if solicitud.estado != SolicitudInscripcion.Estado.EN_REVISION:
        raise ValidationError(
            "Solo una solicitud en revision puede ser rechazada."
        )

    if not motivo or not motivo.strip():
        raise ValidationError(
            "Debe indicar el motivo del rechazo."
        )

    solicitud.estado = SolicitudInscripcion.Estado.RECHAZADA
    solicitud.revisado_por = usuario
    solicitud.fecha_revision = timezone.now()
    solicitud.motivo_rechazo = motivo.strip()

    solicitud.full_clean()
    solicitud.save()

    registrar_auditoria(
        usuario=usuario,
        accion="SOLICITUD_RECHAZADA",
        entidad="SolicitudInscripcion",
        entidad_id=solicitud.pk,
        detalle={
            "jugador_id": solicitud.jugador_id,
            "estado_anterior": "EN_REVISION",
            "estado_nuevo": "RECHAZADA",
        },
    )

    return solicitud

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

def registrar_auditoria(
    *,
    usuario,
    accion,
    entidad,
    entidad_id=None,
    detalle=None,
):
    from .models import Auditoria

    if detalle is None:
        detalle = {}

    return Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        detalle=detalle,
    )