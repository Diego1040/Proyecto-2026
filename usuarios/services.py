from datetime import date

from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from django.db import transaction

from .models import (
    Apoderado,
    ApoderadoJugador,
    Categoria, 
    ReglaCategoria,
    HistorialCategoria,
    Jugador,
    SolicitudInscripcion,
    Usuario,
)
from .validators import normalizar_rut


ACTIVACION_REENVIO_ESPERA_SEGUNDOS = 300


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


def obtener_parentesco_inicial(apoderado):
    parentescos = list(
        apoderado.vinculos_jugadores.filter(activo=True)
        .order_by().values_list("parentesco", flat=True).distinct()[:2]
    )
    return parentescos[0] if len(parentescos) == 1 else ""


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

    calcular_edad(
        fecha_nacimiento,
        fecha_referencia,
    )

    edad_categoria = (
        temporada - fecha_nacimiento.year
    )

    reglas = (
        ReglaCategoria.objects
        .select_related("categoria")
        .filter(
            temporada=temporada,
            activa=True,
            categoria__activa=True,
            edad_min__lte=edad_categoria,
        )
        .filter(
            Q(edad_max__isnull=True)
            | Q(edad_max__gte=edad_categoria)
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

    edad = calcular_edad(jugador.fecha_nacimiento, fecha_referencia)
    if edad >= 18:
        _validar_correo(jugador.email, "El correo del jugador adulto es obligatorio.")
    jugador.full_clean()

    # Permite utilizar tanto un jugador nuevo como uno ya guardado.
    if jugador.pk is None:
        jugador.save()

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

        principal = jugador.vinculos_apoderados.filter(
            activo=True, es_principal=True, puede_gestionar=True,
        ).select_related("apoderado").first()
        if principal is None:
            raise ValidationError("El menor debe tener un apoderado principal que pueda gestionar.")
        _validar_correo(principal.apoderado.email, "El correo del apoderado es obligatorio.")

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
    request=None,
):
    if usuario is None or not usuario.is_authenticated or not usuario.is_staff:
        raise ValidationError(
            "Debe indicar personal administrativo para aprobar la solicitud."
        )

    solicitud = SolicitudInscripcion.objects.select_for_update().select_related(
        "jugador",
    ).get(pk=solicitud.pk)
    if solicitud.estado != SolicitudInscripcion.Estado.EN_REVISION:
        raise ValidationError(
            "Solo una solicitud en revision puede ser aprobada."
        )

    jugador = Jugador.objects.select_for_update().get(pk=solicitud.jugador_id)

    if jugador.categoria_actual_id is None:
        raise ValidationError(
            "El jugador debe tener una categoria asignada "
            "antes de aprobar la solicitud."
        )

    edad = calcular_edad(jugador.fecha_nacimiento)
    if edad >= 18:
        titular = jugador
        _validar_correo(titular.email, "El correo del jugador adulto es obligatorio.")
        if jugador.usuario_id and jugador.usuario.rut != jugador.rut:
            raise ValidationError("La cuenta del jugador tiene otro RUT.")
    else:
        principales = list(
            ApoderadoJugador.objects.select_for_update().select_related("apoderado")
            .filter(jugador=jugador, activo=True, es_principal=True, puede_gestionar=True)[:2]
        )
        if len(principales) != 1:
            raise ValidationError("El menor necesita un único apoderado principal que pueda gestionar.")
        titular = principales[0].apoderado
        _validar_correo(titular.email, "El correo del apoderado es obligatorio.")
        if jugador.usuario_id:
            raise ValidationError("Este flujo no autoriza una cuenta propia para un menor.")

    solicitud.estado = SolicitudInscripcion.Estado.APROBADA
    solicitud.revisado_por = usuario
    solicitud.fecha_revision = timezone.now()
    solicitud.motivo_rechazo = ""
    solicitud.full_clean()
    solicitud.save(update_fields=["estado", "revisado_por", "fecha_revision", "motivo_rechazo"])

    cuenta, requiere_activacion = _preparar_cuenta(titular)

    if titular.usuario_id != cuenta.pk:
        titular.usuario = cuenta
        titular.full_clean()
        titular.save(update_fields=["usuario", "updated_at"])

    solicitud.usuario_autorizado = cuenta
    solicitud.save(update_fields=["usuario_autorizado"])

    jugador.estado = Jugador.Estado.ACTIVO

    if jugador.fecha_ingreso is None:
        jugador.fecha_ingreso = timezone.localdate()

    jugador.full_clean()
    jugador.save()
    solicitud.jugador = jugador

    registrar_auditoria(
        usuario=usuario,
        accion="SOLICITUD_APROBADA",
        entidad="SolicitudInscripcion",
        entidad_id=solicitud.pk,
        detalle={
            "jugador_id": jugador.pk,
            "estado_anterior": "EN_REVISION",
            "estado_nuevo": "APROBADA",
            "usuario_autorizado_id": cuenta.pk,
        },
    )

    if requiere_activacion:
        transaction.on_commit(
            lambda: enviar_enlace_activacion(cuenta.pk, request=request)
        )

    return solicitud


def _validar_correo(correo, mensaje):
    correo = (correo or "").strip()
    if not correo:
        raise ValidationError(mensaje)
    try:
        validate_email(correo)
    except ValidationError as exc:
        raise ValidationError("Debe indicar un correo válido.") from exc
    return correo


def _preparar_cuenta(titular):
    """Solo se llama desde la aprobación, dentro de su transacción."""
    correo = _validar_correo(titular.email, "Debe indicar un correo.")
    rut = normalizar_rut(titular.rut)
    cuenta = Usuario.objects.select_for_update().filter(rut=rut).first()
    if cuenta is None:
        if titular.usuario_id:
            raise ValidationError("El perfil ya está vinculado a otra cuenta.")
        cuenta = Usuario.objects.create_user(
            rut=rut, email=correo, is_active=False,
            first_name=titular.nombres, last_name=titular.apellidos,
        )
        return cuenta, True

    if titular.usuario_id and titular.usuario_id != cuenta.pk:
        raise ValidationError("El perfil ya está vinculado a otra cuenta.")

    if isinstance(titular, Jugador):
        ocupado = Jugador.objects.filter(usuario=cuenta).exclude(pk=titular.pk).exists()
    else:
        ocupado = Apoderado.objects.filter(usuario=cuenta).exclude(pk=titular.pk).exists()
    if ocupado:
        raise ValidationError("La cuenta ya está asociada a otra persona del mismo perfil.")

    if cuenta.is_staff or cuenta.is_superuser:
        if titular.usuario_id != cuenta.pk:
            raise ValidationError("El RUT corresponde a una cuenta administrativa; revise la identidad.")

    if cuenta.email and cuenta.email.casefold() != correo.casefold():
        raise ValidationError("El RUT ya tiene una cuenta con otro correo; revise la identidad.")

    if cuenta.is_active and cuenta.has_usable_password():
        if not cuenta.email:
            if isinstance(titular, Apoderado) and titular.usuario_id == cuenta.pk:
                return cuenta, False
            raise ValidationError("La cuenta existente no tiene correo registrado; revise la identidad.")
        return cuenta, False

    if cuenta.activado_en is not None or cuenta.has_usable_password():
        raise ValidationError("La cuenta está deshabilitada y no puede reactivarse por inscripción.")

    if cuenta.is_active:
        raise ValidationError("La cuenta existente está activa sin contraseña; revise su estado.")

    if not cuenta.email:
        cuenta.email = correo
        cuenta.save(update_fields=["email", "updated_at"])
    return cuenta, True


def cuenta_puede_activarse(cuenta):
    return bool(
        cuenta
        and not cuenta.is_active
        and cuenta.activado_en is None
        and not cuenta.has_usable_password()
        and cuenta.solicitudes_autorizadoras.filter(
            estado=SolicitudInscripcion.Estado.APROBADA,
        ).exists()
    )


def solicitar_activacion(*, rut, correo, request=None):
    """No revela si la combinación consultada corresponde a una cuenta."""
    try:
        rut = normalizar_rut(rut)
    except (TypeError, ValueError):
        return
    cuenta = Usuario.objects.filter(rut=rut, email__iexact=correo.strip()).first()
    if cuenta_puede_activarse(cuenta):
        transaction.on_commit(
            lambda: enviar_enlace_activacion(
                cuenta.pk, request=request, limitar_reenvio=True,
            )
        )


def enviar_enlace_activacion(usuario_id, *, request=None, limitar_reenvio=False):
    cuenta = Usuario.objects.get(pk=usuario_id)
    if not cuenta_puede_activarse(cuenta):
        return
    if limitar_reenvio and not cache.add(
        f"activacion-reenvio:{cuenta.pk}", True,
        timeout=ACTIVACION_REENVIO_ESPERA_SEGUNDOS,
    ):
        return
    uidb64 = urlsafe_base64_encode(force_bytes(cuenta.pk))
    token = default_token_generator.make_token(cuenta)
    ruta = reverse("confirmar_activacion", kwargs={"uidb64": uidb64, "token": token})
    enlace = request.build_absolute_uri(ruta) if request is not None else ruta
    asunto = render_to_string("registration/activacion_subject.txt").strip()
    cuerpo = render_to_string("registration/activacion_email.txt", {"enlace": enlace})
    send_mail(asunto, cuerpo, None, [cuenta.email])


@transaction.atomic
def completar_activacion(*, cuenta, formulario):
    cuenta = Usuario.objects.select_for_update().get(pk=cuenta.pk)
    if not cuenta_puede_activarse(cuenta):
        raise ValidationError("Este enlace de activación ya no está disponible.")
    formulario.user = cuenta
    formulario.save(commit=False)
    cuenta.is_active = True
    cuenta.activado_en = timezone.now()
    cuenta.save(update_fields=["password", "is_active", "activado_en", "updated_at"])
    return cuenta

@transaction.atomic
def rechazar_solicitud_inscripcion(
    *,
    solicitud,
    usuario,
    motivo,
):
    if usuario is None or not usuario.is_authenticated or not usuario.is_staff:
        raise ValidationError(
            "Debe indicar personal administrativo para rechazar la solicitud."
        )

    solicitud = SolicitudInscripcion.objects.select_for_update().get(pk=solicitud.pk)
    if solicitud.estado != SolicitudInscripcion.Estado.EN_REVISION:
        raise ValidationError(
            "Solo una solicitud en revision puede ser rechazada."
        )

    if not motivo or not motivo.strip():
        raise ValidationError(
            "Debe indicar el motivo del rechazo."
        )

    jugador = solicitud.jugador
    if calcular_edad(jugador.fecha_nacimiento) >= 18:
        correo = _validar_correo(jugador.email, "El correo del jugador adulto es obligatorio.")
    else:
        principales = list(
            jugador.vinculos_apoderados.filter(activo=True, es_principal=True)
            .select_related("apoderado")[:2]
        )
        if len(principales) != 1:
            raise ValidationError("El menor necesita un único apoderado principal activo.")
        correo = _validar_correo(
            principales[0].apoderado.email, "El correo del apoderado es obligatorio.",
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

    motivo_rechazo = solicitud.motivo_rechazo
    transaction.on_commit(
        lambda: enviar_correo_rechazo(correo=correo, motivo=motivo_rechazo)
    )

    return solicitud


def enviar_correo_rechazo(*, correo, motivo):
    asunto = render_to_string("registration/rechazo_subject.txt").strip()
    cuerpo = render_to_string("registration/rechazo_email.txt", {"motivo": motivo})
    send_mail(asunto, cuerpo, None, [correo])


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
