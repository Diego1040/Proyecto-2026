"""Operaciones autorizadas y atómicas del área institucional."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from usuarios.services import registrar_auditoria

from .models import Acta, DocumentoNormativo, EventoDisciplinario, Sancion, VersionActa, VersionDocumentoNormativo
from .permisos import (
    GRUPO_MIEMBROS, puede_gestionar_miembros, puede_gestionar_normativa,
    puede_publicar_normativa,
    puede_gestionar_actas, puede_publicar_actas,
    puede_consultar_sanciones, puede_corregir_sanciones,
    puede_registrar_sanciones, puede_resolver_sanciones,
)
from .validators import validar_pdf


def exigir(condicion):
    if not condicion:
        raise PermissionDenied


def verificar_adjunto(version, obligatorio=False):
    if not version.archivo:
        if obligatorio:
            raise ValidationError("Adjunta el PDF antes de publicar.")
        return
    try:
        with version.archivo.open("rb") as archivo:
            datos = validar_pdf(archivo)
    except FileNotFoundError as error:
        raise ValidationError("El PDF no está disponible. Vuelve a adjuntarlo en el borrador.") from error
    if datos["sha256"] != version.archivo_sha256:
        raise ValidationError("El PDF cambió desde su registro. Vuelve a adjuntarlo en el borrador.")


def _foto_version(version):
    """Sólo metadatos: los textos de las actas permanecen en sus versiones."""
    campos = ("estado", "archivo_sha256", "archivo_tamano", "numero", "publicado_por_id")
    datos = {campo: getattr(version, campo) for campo in campos}
    if isinstance(version, VersionActa):
        datos["acta_id"] = version.acta_id
        campos = ("fecha_reunion", "publicado_en")
    else:
        datos["documento_id"] = version.documento_id
        campos = ("titulo", "motivo_cambio", "archivo_nombre", "version", "visibilidad", "fecha_documento", "vigente_desde", "publicado_en")
    for campo in campos:
        valor = getattr(version, campo)
        datos[campo] = valor.isoformat() if hasattr(valor, "isoformat") else valor
    return datos


def _detalle_version(version, antes=None, campos_modificados=None):
    despues = _foto_version(version)
    antes = antes or {}
    if campos_modificados is None:
        campos_modificados = [campo for campo, valor in despues.items() if antes.get(campo) != valor]
    return {"version_id": version.pk, "campos_modificados": sorted(set(campos_modificados)),
            "antes": antes, "despues": despues}


def _guardar_version(version, archivo, usuario, accion, antes=None, campos_modificados=None):
    """Si falla la escritura en BD o la auditoría, descarta sólo el archivo nuevo."""
    nuevo = None
    anterior = version.archivo.name if version.archivo else None
    try:
        if archivo:
            datos = validar_pdf(archivo)
            version.archivo_nombre = datos["nombre"]
            version.archivo_sha256 = datos["sha256"]
            version.archivo_tamano = datos["tamano"]
        version.full_clean(exclude=["archivo"])
        if archivo:
            version.archivo.save(datos["nombre"], archivo, save=False)
            nuevo = version.archivo.name
        version.save()
        detalle = _detalle_version(version, antes, campos_modificados)
        if archivo:
            detalle["campos_modificados"] = sorted(set(detalle["campos_modificados"]) | {"archivo"})
        registrar_auditoria(
            usuario=usuario, accion=accion, entidad=version._meta.object_name,
            entidad_id=version.pk, detalle=detalle,
        )
    except Exception:
        if nuevo:
            version.archivo.storage.delete(nuevo)
        raise
    if nuevo and anterior and anterior != nuevo:
        transaction.on_commit(lambda: version.archivo.storage.delete(anterior))
    return version


@transaction.atomic
def crear_documento(*, usuario, codigo, tipo, datos, archivo=None):
    exigir(puede_gestionar_normativa(usuario))
    documento = DocumentoNormativo(codigo=codigo, tipo=tipo, creado_por=usuario)
    documento.full_clean()
    documento.save()
    return nueva_version_documento(usuario=usuario, documento_id=documento.pk, datos=datos, archivo=archivo)


@transaction.atomic
def nueva_version_documento(*, usuario, documento_id, datos, archivo=None):
    exigir(puede_gestionar_normativa(usuario))
    documento = DocumentoNormativo.objects.select_for_update().get(pk=documento_id)
    numero = (documento.versiones.aggregate(n=Max("numero"))["n"] or 0) + 1
    if numero > 1 and not datos.get("motivo_cambio", "").strip():
        raise ValidationError("Justifica la creación de la nueva versión.")
    if documento.versiones.filter(estado=VersionDocumentoNormativo.Estado.BORRADOR).exists():
        raise ValidationError("Primero termina el borrador existente.")
    version = VersionDocumentoNormativo(
        documento=documento, numero=numero, creada_por=usuario,
        visibilidad=datos.get("visibilidad", VersionDocumentoNormativo.Visibilidad.INTERNO),
        **{campo: datos[campo] for campo in ("titulo", "version", "fecha_documento", "vigente_desde", "motivo_cambio")},
    )
    return _guardar_version(version, archivo, usuario, "NORMATIVA_BORRADOR_CREADO")


@transaction.atomic
def editar_documento(*, usuario, version_id, datos, archivo=None):
    exigir(puede_gestionar_normativa(usuario))
    version = VersionDocumentoNormativo.objects.select_for_update().get(pk=version_id)
    if version.estado != version.Estado.BORRADOR:
        raise ValidationError("Para corregir una publicación crea una nueva versión.")
    antes = _foto_version(version)
    for campo in ("titulo", "version", "fecha_documento", "vigente_desde", "motivo_cambio"):
        setattr(version, campo, datos[campo])
    if "visibilidad" in datos:
        version.visibilidad = datos["visibilidad"]
    if version.numero > 1 and not version.motivo_cambio.strip():
        raise ValidationError("La nueva versión requiere justificación.")
    return _guardar_version(version, archivo, usuario, "NORMATIVA_BORRADOR_MODIFICADO", antes)


@transaction.atomic
def publicar_documento(*, usuario, version_id):
    exigir(puede_publicar_normativa(usuario))
    version = VersionDocumentoNormativo.objects.select_for_update().get(pk=version_id)
    DocumentoNormativo.objects.select_for_update().get(pk=version.documento_id)
    if version.estado != version.Estado.BORRADOR:
        raise ValidationError("Esta versión ya fue publicada.")
    verificar_adjunto(version, obligatorio=True)
    if version.vigente_desde > timezone.localdate():
        raise ValidationError("No se permite publicación programada; la vigencia debe comenzar hoy o antes.")
    antes = _foto_version(version)
    for vigente in version.documento.versiones.filter(estado=version.Estado.VIGENTE):
        antes_vigente = _foto_version(vigente)
        vigente.estado = version.Estado.HISTORICA
        vigente.save(update_fields=["estado", "actualizada_en"])
        detalle = _detalle_version(vigente, antes_vigente, ["estado"])
        detalle["reemplazada_por"] = version.pk
        registrar_auditoria(usuario=usuario, accion="NORMATIVA_VIGENCIA_FINALIZADA",
                            entidad="VersionDocumentoNormativo", entidad_id=vigente.pk,
                            detalle=detalle)
    version.estado = version.Estado.VIGENTE
    version.publicado_por = usuario
    version.publicado_en = timezone.now()
    version.full_clean()
    version.save()
    registrar_auditoria(usuario=usuario, accion="NORMATIVA_PUBLICADA", entidad="VersionDocumentoNormativo",
                        entidad_id=version.pk, detalle=_detalle_version(version, antes, ["estado", "publicado_por", "publicado_en"]))
    return version


@transaction.atomic
def autorizar_miembro(*, usuario, destinatario, autorizar, motivo):
    from django.contrib.auth.models import Group

    exigir(puede_gestionar_miembros(usuario))
    if not motivo.strip():
        raise ValidationError("Registra el motivo de la autorización o revocación.")
    if autorizar and not destinatario.is_active:
        raise ValidationError("La cuenta debe estar activa antes de autorizarla.")
    grupo = Group.objects.get(name=GRUPO_MIEMBROS)
    antes = destinatario.groups.filter(pk=grupo.pk).exists()
    if antes == autorizar:
        raise ValidationError("La cuenta ya tiene ese estado de autorización.")
    if autorizar:
        destinatario.groups.add(grupo)
    else:
        destinatario.groups.remove(grupo)
    registrar_auditoria(usuario=usuario, accion="MIEMBRO_AUTORIZADO" if autorizar else "MIEMBRO_REVOCADO",
                        entidad="Usuario", entidad_id=destinatario.pk,
                        detalle={"grupo": GRUPO_MIEMBROS, "antes": antes, "despues": autorizar, "motivo": motivo})


@transaction.atomic
def crear_acta(*, usuario, codigo, datos, archivo=None):
    exigir(puede_gestionar_actas(usuario))
    acta = Acta(codigo=codigo, creado_por=usuario)
    acta.full_clean()
    acta.save()
    return nueva_version_acta(usuario=usuario, acta_id=acta.pk, datos=datos, archivo=archivo)


@transaction.atomic
def nueva_version_acta(*, usuario, acta_id, datos, archivo=None):
    exigir(puede_gestionar_actas(usuario))
    acta = Acta.objects.select_for_update().get(pk=acta_id)
    numero = (acta.versiones.aggregate(n=Max("numero"))["n"] or 0) + 1
    if numero > 1 and not datos.get("motivo_cambio", "").strip():
        raise ValidationError("La corrección de un acta requiere justificación.")
    if acta.versiones.filter(estado=VersionActa.Estado.BORRADOR).exists():
        raise ValidationError("Primero termina el borrador existente.")
    version = VersionActa(acta=acta, numero=numero, creada_por=usuario,
                          **{campo: datos[campo] for campo in ("titulo", "fecha_reunion", "acuerdos", "motivo_cambio")})
    return _guardar_version(version, archivo, usuario, "ACTA_BORRADOR_CREADO",
                            campos_modificados=["titulo", "fecha_reunion", "acuerdos", "motivo_cambio"])


@transaction.atomic
def editar_acta(*, usuario, version_id, datos, archivo=None):
    exigir(puede_gestionar_actas(usuario))
    version = VersionActa.objects.select_for_update().get(pk=version_id)
    if version.estado != version.Estado.BORRADOR:
        raise ValidationError("Para corregir una publicación crea una nueva versión.")
    antes = _foto_version(version)
    campos = ("titulo", "fecha_reunion", "acuerdos", "motivo_cambio")
    modificados = [campo for campo in campos if getattr(version, campo) != datos[campo]]
    for campo in campos:
        setattr(version, campo, datos[campo])
    if version.numero > 1 and not version.motivo_cambio.strip():
        raise ValidationError("La corrección requiere justificación.")
    return _guardar_version(version, archivo, usuario, "ACTA_BORRADOR_MODIFICADO", antes, modificados)


@transaction.atomic
def publicar_acta(*, usuario, version_id):
    exigir(puede_publicar_actas(usuario))
    version = VersionActa.objects.select_for_update().get(pk=version_id)
    Acta.objects.select_for_update().get(pk=version.acta_id)
    if version.estado != version.Estado.BORRADOR:
        raise ValidationError("Esta versión ya está publicada.")
    if version.numero > 1 and not version.motivo_cambio.strip():
        raise ValidationError("La corrección requiere justificación.")
    verificar_adjunto(version)
    antes = _foto_version(version)
    version.estado = version.Estado.PUBLICADA
    version.publicado_en = timezone.now()
    version.publicado_por = usuario
    version.full_clean()
    version.save()
    registrar_auditoria(usuario=usuario, accion="ACTA_PUBLICADA", entidad="VersionActa", entidad_id=version.pk,
                        detalle=_detalle_version(version, antes, ["estado", "publicado_por", "publicado_en"]))
    return version


def _foto_sancion(sancion):
    return {"jugador_id": sancion.jugador_id, "jugador": str(sancion.jugador),
            "fecha": sancion.fecha.isoformat(), "motivo": sancion.motivo,
            "resolucion": sancion.resolucion, "estado": sancion.estado,
            "revision": sancion.revision}


def _evento_privado(sancion, usuario, accion, *, antes=None, justificacion=""):
    # Nunca enviar contenido ni referencias de expedientes a la auditoría general.
    return EventoDisciplinario.objects.create(
        sancion=sancion, actor=usuario, accion=accion, justificacion=justificacion,
        antes=antes or {}, despues=_foto_sancion(sancion) if accion != "CONSULTADA" else {},
    )


@transaction.atomic
def registrar_sancion(*, usuario, jugador, fecha, motivo):
    exigir(puede_registrar_sanciones(usuario))
    sancion = Sancion(jugador=jugador, fecha=fecha, motivo=motivo.strip(), creada_por=usuario, actualizada_por=usuario)
    sancion.full_clean()
    sancion.save()
    _evento_privado(sancion, usuario, "REGISTRADA")
    return sancion


def _sancion_actual(sancion_id, revision):
    sancion = Sancion.objects.select_for_update().select_related("jugador").get(pk=sancion_id)
    if sancion.revision != revision:
        raise ValidationError("El expediente cambió desde que abriste el formulario. Actualiza antes de continuar.")
    if sancion.estado == Sancion.Estado.ANULADA:
        raise ValidationError("El expediente anulado se conserva sin nuevas modificaciones.")
    return sancion


def _guardar_sancion(sancion, usuario, accion, antes, justificacion=""):
    revision = sancion.revision
    sancion.revision += 1
    sancion.actualizada_por = usuario
    sancion.actualizada_en = timezone.now()
    sancion.full_clean()
    campos = ("jugador_id", "fecha", "motivo", "resolucion", "estado", "resuelta_por_id", "resuelta_en", "revision", "actualizada_por_id", "actualizada_en")
    # La comparación de revisión también evita escrituras obsoletas en SQLite,
    # donde select_for_update no proporciona un bloqueo de fila.
    actualizadas = Sancion.objects.filter(pk=sancion.pk, revision=revision).update(**{campo: getattr(sancion, campo) for campo in campos})
    if actualizadas != 1:
        raise ValidationError("Otro integrante modificó el expediente. Actualiza antes de continuar.")
    _evento_privado(sancion, usuario, accion, antes=antes, justificacion=justificacion)
    return sancion


@transaction.atomic
def corregir_sancion(*, usuario, sancion_id, revision, jugador, fecha, motivo, resolucion, justificacion):
    exigir(puede_corregir_sanciones(usuario))
    if not justificacion.strip():
        raise ValidationError("Toda corrección requiere justificación.")
    sancion = _sancion_actual(sancion_id, revision)
    antes = _foto_sancion(sancion)
    sancion.jugador, sancion.fecha = jugador, fecha
    sancion.motivo, sancion.resolucion = motivo.strip(), resolucion.strip()
    return _guardar_sancion(sancion, usuario, "CORREGIDA", antes, justificacion.strip())


@transaction.atomic
def resolver_sancion(*, usuario, sancion_id, revision, resolucion):
    exigir(puede_resolver_sanciones(usuario))
    if not resolucion.strip():
        raise ValidationError("La resolución es obligatoria.")
    sancion = _sancion_actual(sancion_id, revision)
    if sancion.estado != Sancion.Estado.REGISTRADA:
        raise ValidationError("Sólo se puede resolver un expediente registrado.")
    antes = _foto_sancion(sancion)
    sancion.estado, sancion.resolucion = Sancion.Estado.RESUELTA, resolucion.strip()
    sancion.resuelta_por, sancion.resuelta_en = usuario, timezone.now()
    return _guardar_sancion(sancion, usuario, "RESUELTA", antes)


@transaction.atomic
def anular_sancion(*, usuario, sancion_id, revision, resolucion, justificacion):
    exigir(puede_resolver_sanciones(usuario))
    if not justificacion.strip() or not resolucion.strip():
        raise ValidationError("La anulación requiere justificación y resolución.")
    sancion = _sancion_actual(sancion_id, revision)
    antes = _foto_sancion(sancion)
    sancion.estado, sancion.resolucion = Sancion.Estado.ANULADA, resolucion.strip()
    sancion.resuelta_por, sancion.resuelta_en = usuario, timezone.now()
    return _guardar_sancion(sancion, usuario, "ANULADA", antes, justificacion.strip())


@transaction.atomic
def consultar_sancion(*, usuario, sancion_id):
    exigir(puede_consultar_sanciones(usuario))
    sancion = Sancion.objects.select_related("jugador", "creada_por", "actualizada_por", "resuelta_por").get(pk=sancion_id)
    _evento_privado(sancion, usuario, "CONSULTADA")
    return sancion
