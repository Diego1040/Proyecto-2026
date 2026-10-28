"""Autorización de dominio. Nunca utiliza el bypass de superusuarios."""

from django.db.models import Q
from django.utils import timezone

from usuarios.models import Apoderado, ApoderadoJugador, Jugador, SolicitudInscripcion
from usuarios.validators import normalizar_rut


GRUPO_ADMINISTRACION = "Administración"
GRUPO_SECRETARIA = "Secretaría"
GRUPO_COMITE = "Comité de Disciplina"
GRUPO_MIEMBROS = "Miembros autorizados"
ROLES_DEL_CLUB = (GRUPO_ADMINISTRACION, GRUPO_SECRETARIA, "Tesorería", "Entrenador", GRUPO_COMITE)


def cuenta_habilitada(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.is_active)


def permiso_de_grupo(usuario, grupo, permiso):
    return cuenta_habilitada(usuario) and usuario.groups.filter(
        name=grupo, permissions__content_type__app_label="institucional",
        permissions__codename=permiso,
    ).exists()


def puede_gestionar_normativa(usuario):
    return permiso_de_grupo(usuario, GRUPO_ADMINISTRACION, "change_documentonormativo")


def puede_publicar_normativa(usuario):
    return permiso_de_grupo(usuario, GRUPO_ADMINISTRACION, "publicar_documentonormativo")


def puede_gestionar_miembros(usuario):
    return permiso_de_grupo(usuario, GRUPO_ADMINISTRACION, "gestionar_miembros")


def es_miembro_autorizado(usuario):
    if not cuenta_habilitada(usuario):
        return False
    # Estos roles sólo los asigna personal autorizado; no existe autoinscripción
    # a grupos. Ser staff/superusuario o tener is_active no acredita pertenencia.
    if usuario.groups.filter(name__in=ROLES_DEL_CLUB).exists():
        return True
    jugador = Jugador.objects.filter(usuario_id=usuario.pk).first()
    apoderado = Apoderado.objects.filter(usuario_id=usuario.pk).first()
    identidad_jugador = jugador is not None and normalizar_rut(jugador.rut) == normalizar_rut(usuario.rut)
    identidad_apoderado = apoderado is not None and normalizar_rut(apoderado.rut) == normalizar_rut(usuario.rut)
    vinculos = ApoderadoJugador.objects.filter(
        apoderado__usuario_id=usuario.pk, activo=True, puede_gestionar=True,
    ).exclude(jugador__estado=Jugador.Estado.PENDIENTE)
    # La inscripción pública no crea ni vincula cuentas. Una credencial habilitada
    # y un perfil no pendiente del mismo RUT acreditan la vinculación administrativa,
    # también para históricos de HU19 sin SolicitudInscripcion. La mera fecha de
    # activación, sin rol ni perfil legítimo, no es suficiente.
    if usuario.has_usable_password() and (
        (identidad_jugador and jugador.estado != Jugador.Estado.PENDIENTE)
        or (identidad_apoderado and vinculos.exists())
    ):
        return True
    deportivos = Jugador.objects.filter(
        Q(estado=Jugador.Estado.ACTIVO)
        | Q(estado=Jugador.Estado.INACTIVO,
            periodos_inactividad__fecha_reactivacion__isnull=True,
            periodos_inactividad__fecha_inicio__lte=timezone.localdate()),
        solicitudes_inscripcion__estado=SolicitudInscripcion.Estado.APROBADA,
        solicitudes_inscripcion__usuario_autorizado=usuario,
    )
    if (identidad_jugador and deportivos.filter(usuario=usuario).exists()) or (identidad_apoderado and deportivos.filter(
        vinculos_apoderados__apoderado__usuario=usuario,
        vinculos_apoderados__activo=True,
        vinculos_apoderados__puede_gestionar=True,
    ).exists()):
        return True
    if not permiso_de_grupo(usuario, GRUPO_MIEMBROS, "consultar_documentos_institucionales"):
        return False
    # La autorización manual no convierte una inscripción pendiente en aprobada
    # ni restaura un vínculo de representación revocado.
    if Jugador.objects.filter(usuario=usuario, estado=Jugador.Estado.PENDIENTE).exists():
        return False
    if jugador and not identidad_jugador:
        return False
    if apoderado and (not identidad_apoderado or not vinculos.exists()):
        return False
    return True


def puede_consultar_normativa(usuario):
    return puede_gestionar_normativa(usuario) or es_miembro_autorizado(usuario)


def puede_gestionar_actas(usuario):
    return permiso_de_grupo(usuario, GRUPO_SECRETARIA, "change_acta")


def puede_publicar_actas(usuario):
    return permiso_de_grupo(usuario, GRUPO_SECRETARIA, "publicar_acta")


def puede_consultar_actas(usuario):
    return puede_gestionar_actas(usuario) or es_miembro_autorizado(usuario)


def puede_acceder(usuario):
    return puede_consultar_actas(usuario) or puede_consultar_normativa(usuario) or puede_consultar_sanciones(usuario)


def puede_consultar_sanciones(usuario):
    return permiso_de_grupo(usuario, GRUPO_COMITE, "view_sancion")


def puede_registrar_sanciones(usuario):
    return permiso_de_grupo(usuario, GRUPO_COMITE, "add_sancion")


def puede_corregir_sanciones(usuario):
    return permiso_de_grupo(usuario, GRUPO_COMITE, "change_sancion")


def puede_resolver_sanciones(usuario):
    return permiso_de_grupo(usuario, GRUPO_COMITE, "resolver_sancion")
