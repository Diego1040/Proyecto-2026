"""Regla de negocio de la asistencia"""

from datetime import datetime, time, timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from usuarios.models import AlertaSalud, Categoria
from .models import Evento
from .permisos import categorias_visibles, es_entrenador
from usuarios.models import Jugador
from usuarios.services import registrar_auditoria
from finanzas.services import jugador_bloqueado_por_morosidad

from .models import Asistencia, Nomina, NominaJugador, ReporteLesion
from .permisos import es_administracion


PLAZO_EDICION_HORAS = 48

def es_entrenamiento_antiguo(entrenamiento, ahora=None):
    """True si ya paso el plazo para que el entrenador edite."""
    if ahora is None:
        ahora = timezone.localtime()

    fin_del_dia = timezone.make_aware(datetime.combine(entrenamiento.fecha, time.max))
    return ahora > fin_del_dia + timedelta(hours=PLAZO_EDICION_HORAS)

def puede_modificar(usuario, entrenamiento):
    """El entrenador edita dentro del plazo; Administracion siempre puede."""
    if es_administracion(usuario):
        return True
    return not es_entrenamiento_antiguo(entrenamiento)

def jugadores_del_entrenamiento(entrenamiento):
    """Devuelve los jugadores que pueden asistir a un entrenamiento."""
    return (Jugador.objects.filter(categoria_actual=entrenamiento.categoria, estado=Jugador.Estado.ACTIVO).order_by('nombres', 'apellidos'))

@transaction.atomic
def registrar_asistencia(*, entrenamiento, usuario, estados, motivo=""):
    """
    Guarda la asistencia de los jugadores a un entrenamiento.
    
    estados: diccionario {jugador_id: estado}
    """
    if not puede_modificar(usuario, entrenamiento):
        raise ValidationError(f"Pasaron mas de {PLAZO_EDICION_HORAS} horas desde el entrenamiento, Solo los administradores pueden modificar.")

    antiguo = es_entrenamiento_antiguo(entrenamiento)

    if antiguo and not motivo.strip():
        raise ValidationError("Para modificar un entrenamiento antiguo, debe indicar un motivo.")

    validos = set(Asistencia.Estado.values)
    jugadores = {
        j.pk: j for j in jugadores_del_entrenamiento(entrenamiento)
    }

    guardadas = 0

    for jugador_id, estado in estados.items():
        if estado not in validos:
            raise ValidationError("Estado de asistencia invalido.")

        jugador = jugadores.get(jugador_id)
        if jugador is None:
            continue

        Asistencia.objects.update_or_create(
            entrenamiento=entrenamiento,
            jugador=jugador,
            defaults={
                'estado': estado,
                'registrado_por': usuario,
                'motivo_modificacion': motivo if antiguo else "",
            },
        )

        guardadas += 1

    if antiguo:
        registrar_auditoria(
            usuario=usuario,
            accion="ASISTENCIA_MODIFICADA_FUERA_DE_PLAZO",
            entidad="Entrenamiento",
            entidad_id=entrenamiento.pk,
            detalle={"motivo": motivo.strip(), "jugadores": guardadas},
        )

    return guardadas

def resumen_asistencia_mes(jugador, hoy=None):
    """
    Asistencia del jugador en el mes actual.

    Cuenta solo los entrenamientos en que se paso lista.
    """
    if hoy is None:
        hoy = timezone.localdate()

    registros = Asistencia.objects.filter(
        jugador=jugador,
        entrenamiento__fecha__year=hoy.year,
        entrenamiento__fecha__month=hoy.month,
    )

    total = registros.count()
    presentes = registros.filter(estado=Asistencia.Estado.PRESENTE).count()
    justificadas = registros.filter(estado=Asistencia.Estado.JUSTIFICADO).count()
    ausentes = registros.filter(estado=Asistencia.Estado.AUSENTE).count()

    return {
        "total": total,
        "presentes": presentes,
        "ausentes": ausentes,
        "justificadas": justificadas,
        "porcentaje": round(presentes * 100 / total) if total else None,
    }

#HU-06
def responsables_posibles(categoria):
    """Entreadores que tienen una categoria asignada"""
    from django.contrib.auth import get_user_model

    return (
        get_user_model().objects.filter(
            is_active=True,
            groups__name="Entrenador",
            perfil_entrenador__categorias=categoria,
        )
        .distinct()
        .order_by("first_name", "last_name", "rut")
    )

def validar_planificacion(*, categoria, nombre, fecha, hora_inicio, duracion, objetivo, responsable):
    """Revisa los datos que son obligatorios de HU-06 y devuelve la lista de errores"""
    errores = []

    if not nombre:
        errores.append("Escribe un nombre para el entrenamiento.")
    if not fecha:
        errores.append("Indica la fecha del entrenamiento.")
    if not hora_inicio:
        errores.append("Indica la hora del entrenamiento.")
    if duracion < 1:
        errores.append("La duración debe ser de al menos 1 minuto.")
    if not objetivo:
        errores.append("Escribe el objetivo del entrenamiento.")
    if responsable is None:
        errores.append("Elige el entrenador responsable.")
    elif categoria is not None and not responsables_posibles(categoria).filter(pk=responsable.pk).exists():
        errores.append("El responsable debe ser un entrenador de esa categoría.")

    return errores

def puede_editar_planificacion(usuario, entrenamiento):
    """
    La planificacion se puede cambiar hasta el dia del entrenamiento.
    Despues de eso solo Administracion puede corregirla.
    """
    if es_administracion(usuario):
        return True
    return entrenamiento.fecha >= timezone.localdate()

CAMPOS_PLANIFICACION = ["nombre", "fecha", "hora_inicio", "duracion", "objetivo", "responsable"]

def _valor_legible(entrenamiento, campo):
    valor = getattr(entrenamiento, campo)
    if valor is None:
        return ""
    if campo == "responsable":
        return valor.get_full_name() or str(valor)
    if campo == "fecha":
        return valor.strftime("%d/%m/%Y")
    if campo == "hora_inicio":
        return valor.strftime("%H:%M")
    return str(valor)

@transaction.atomic
def actualizar_planificacion(*, entrenamiento, usuario, datos):
    """
    Guarda los cambios de la planificacion y deja el historial
    (antes y despues de cada campo) en la auditoria.
    """
    if not puede_editar_planificacion(usuario, entrenamiento):
        raise ValidationError(
            "El entrenamiento ya pasó. Solo Administración puede modificarlo."
        )
    antes = {c: _valor_legible(entrenamiento, c) for c in CAMPOS_PLANIFICACION}

    for campo, valor in datos.items():
        setattr(entrenamiento, campo, valor)
    entrenamiento.save()
    entrenamiento.refresh_from_db()

    despues = {c: _valor_legible(entrenamiento, c) for c in CAMPOS_PLANIFICACION}
    cambios = {
        c: {"antes": antes[c], "despues": despues[c]}
        for c in CAMPOS_PLANIFICACION
        if antes[c] != despues[c]
    }

    if cambios:
        registrar_auditoria(
            usuario=usuario,
            accion="PLANIFICACION_MODIFICADA",
            entidad="Entrenamiento",
            entidad_id=entrenamiento.pk,
            detalle=cambios,
        )

    return cambios

def historial_planificacion(entrenamiento):
    """Cambios registrados de un entrenamiento, del mas reciente al mas antiguo."""
    from usuarios.models import Auditoria

    return (
        Auditoria.objects
        .filter(
            entidad="Entrenamiento",
            entidad_id=entrenamiento.pk,
            accion__in=["PLANIFICACION_CREADA", "PLANIFICACION_MODIFICADA"],
        )
        .select_related("usuario")
        .order_by("-fecha")
    )

def puede_publicar_eventos(usuario):
    """Admnistración y entrenadores pueden publicar eventos"""
    return es_administracion(usuario) or es_entrenador(usuario)

def categorias_del_usuario(usuario):
    """
    Categorías cuyo calendario puede consultar el usuario.
    - Administración: todas las activas.
    - Entrenador: sus categorías asignadas.
    - Jugador: su categoría actual.
    - Apoderado: las categorías de sus jugadores vinculados.
    Un usuario puede tener varios perfiles, por eso se suman.
    """
    if es_administracion(usuario):
        return Categoria.objects.filter(activa=True)

    ids = set(categorias_visibles(usuario).values_list("pk", flat=True))

    jugador = getattr(usuario, "jugador", None)
    if jugador and jugador.categoria_actual_id:
        ids.add(jugador.categoria_actual_id)

    apoderado = getattr(usuario, "apoderado", None)
    if apoderado:
        ids.update(
            apoderado.vinculos_jugadores.filter(activo=True, jugador__categoria_actual__isnull=False).values_list("jugador__categoria_actual_id", flat=True)
        )

    return Categoria.objects.filter(pk__in=ids)

def eventos_visibles(usuario, categoria=None, desde=None):
    """
    Eventos que ve el usuario: los de sus categorías y los de todo el club.
    Si se indica una categoría, filtra solo esa (más los del club).
    """
    categorias = categorias_del_usuario(usuario)
    if categoria is not None:
        categorias = categorias.filter(pk=categoria.pk)

    eventos = Evento.objects.filter(Q(categoria__in=categorias) | Q(categoria__isnull=True)).select_related("categoria")
    if desde is not None:
        eventos = eventos.filter(fecha__gte=desde)

    return eventos.order_by("fecha", "hora")

def validar_evento(*, usuario, tipo, titulo, categoria, categoria_pedida, fecha, hora, lugar):
    """Devuelve la lista de errores del formulario de evento (vacía = OK)."""
    errores = []

    if tipo not in Evento.Tipo.values:
        errores.append("Selecciona un tipo de evento válido.")
    if not titulo:
        errores.append("El título es obligatorio.")
    if not fecha:
        errores.append("La fecha es obligatoria.")
    elif fecha < timezone.localdate():
        errores.append("No se pueden publicar eventos en fechas pasadas.")
    if not hora:
        errores.append("La hora es obligatoria.")
    if not lugar:
        errores.append("El lugar es obligatorio.")

    # Pidió una categoría pero no es una de las suyas
    if categoria_pedida and categoria is None:
        errores.append("No puedes publicar eventos para esa categoría.")
    # Solo Administración publica eventos para todo el club
    if not categoria_pedida and not es_administracion(usuario):
        errores.append("Solo Administración puede publicar eventos para todo el club.")

    return errores

def puede_eliminar_evento(usuario, evento):
    """Administración elimina cualquiera; el entrenador solo los que creó."""
    return es_administracion(usuario) or evento.creado_por_id == usuario.pk

DIAS_ASISTENCIA_NOMINA = 30
MAX_JUGADORES_NOMINA = 12

def asistencia_reciente(jugador, dias=DIAS_ASISTENCIA_NOMINA, hoy=None):
    """Porcentaje de asistencia del jugador en los últimos días (None si no hay registros)."""
    if hoy is None:
        hoy = timezone.localdate()

    registros = Asistencia.objects.filter(
        jugador=jugador,
        entrenamiento__fecha__gt=hoy - timedelta(days=dias),
        entrenamiento__fecha__lte=hoy,
    )
    total = registros.count()
    if not total:
        return None
    presentes = registros.filter(estado=Asistencia.Estado.PRESENTE).count()
    return round(presentes * 100 / total)


def candidatos_nomina(categoria):
    """
    Jugadores activos de la categoría con su asistencia reciente.
    No se excluye a nadie por deudas: la selección es manual del entrenador.
    """
    jugadores = Jugador.objects.filter(
        categoria_actual=categoria,
        estado=Jugador.Estado.ACTIVO,
    ).order_by("apellidos", "nombres")

    restricciones = restricciones_vigentes(jugadores)
    return [
        {"jugador": j, "asistencia": asistencia_reciente(j), "restriccion": restricciones.get(j.pk)}
        for j in jugadores
    ]


def partidos_para_nomina(categorias):
    """Partidos y campeonatos próximos del calendario (HU-10) de esas categorías."""
    return (
        Evento.objects
        .filter(
            tipo__in=[Evento.Tipo.PARTIDO, Evento.Tipo.CAMPEONATO],
            categoria__in=categorias,
            fecha__gte=timezone.localdate(),
        )
        .select_related("categoria")
        .order_by("fecha", "hora")
    )


@transaction.atomic
def crear_nomina(*, usuario, categoria, titulo, fecha, lugar="", evento=None, jugador_ids=(), observaciones=""):
    """Valida y guarda la nómina con sus jugadores. Lanza ValidationError con la lista de errores."""
    errores = []

    if categoria is None:
        errores.append("Selecciona una categoría válida.")
    if not titulo:
        errores.append("Escribe el partido o rival de la nómina.")
    if not fecha:
        errores.append("Indica la fecha del partido.")
    if evento is not None and categoria is not None and evento.categoria_id != categoria.pk:
        errores.append("El partido elegido no es de esa categoría.")

    ids = {int(i) for i in jugador_ids if str(i).isdigit()}
    candidatos = {c["jugador"].pk: c for c in candidatos_nomina(categoria)} if categoria else {}
    elegidos = [candidatos[i] for i in ids if i in candidatos]

    if not elegidos:
        errores.append("Selecciona al menos un jugador.")
    elif len(elegidos) > MAX_JUGADORES_NOMINA:
        errores.append(f"La nómina admite como máximo {MAX_JUGADORES_NOMINA} jugadores.")
    if len(elegidos) != len(ids):
        errores.append("Hay jugadores que no pertenecen a la categoría o no están activos.")

    for candidato in elegidos:
        jugador = candidato["jugador"]

        if jugador_bloqueado_por_morosidad(jugador):
            errores.append(
                f"{jugador.nombres} {jugador.apellidos} no puede incluirse "
                "en la nómina porque acumula dos o más mensualidades "
                "vencidas e impagas."
            )

    if errores:
        raise ValidationError(errores)

    nomina = Nomina.objects.create(
        categoria=categoria,
        evento=evento,
        titulo=titulo,
        fecha=fecha,
        lugar=lugar,
        observaciones=observaciones,
        creado_por=usuario,
    )
    NominaJugador.objects.bulk_create([
        NominaJugador(nomina=nomina, jugador=c["jugador"], asistencia_porcentaje=c["asistencia"])
        for c in elegidos
    ])

    registrar_auditoria(
        usuario=usuario,
        accion="NOMINA_GENERADA",
        entidad="Nomina",
        entidad_id=nomina.pk,
        detalle={"titulo": titulo, "fecha": str(fecha), "jugadores": len(elegidos)},
    )
    return nomina

def nominas_visibles(usuario):
    """Nóminas de las categorías que el usuario puede ver (Administración: todas)."""
    return (
        Nomina.objects
        .filter(categoria__in=categorias_visibles(usuario))
        .select_related("categoria", "creado_por")
    )

# HU-20
def filtrar_nominas(nominas, *, categoria=None, desde=None, hasta=None, texto=""):
    """Aplica los filtros del historial a un queryset de nóminas."""
    if categoria is not None:
        nominas = nominas.filter(categoria=categoria)
    if desde:
        nominas = nominas.filter(fecha__gte=desde)
    if hasta:
        nominas = nominas.filter(fecha__lte=hasta)
    if texto:
        nominas = nominas.filter(
            Q(titulo__icontains=texto)
            | Q(lugar__icontains=texto)
            | Q(integrantes__jugador__nombres__icontains=texto)
            | Q(integrantes__jugador__apellidos__icontains=texto)
        ).distinct()
    return nominas
# FIN NUEVO (HU-20)

# HU-08
def jugadores_que_puede_reportar(usuario):
    """El jugador sobre sí mismo y el apoderado sobre sus jugadores vinculados que puede gestionar."""
    ids = set()
 
    jugador = getattr(usuario, "jugador", None)
    if jugador:
        ids.add(jugador.pk)
 
    apoderado = getattr(usuario, "apoderado", None)
    if apoderado:
        ids.update(
            apoderado.vinculos_jugadores
            .filter(activo=True, puede_gestionar=True)
            .values_list("jugador_id", flat=True)
        )
 
    return Jugador.objects.filter(pk__in=ids).order_by("nombres", "apellidos")
 
 
def puede_revisar_lesiones(usuario):
    return es_administracion(usuario) or es_entrenador(usuario)
 
 
def reportes_para_revisar(usuario):
    """Reportes de los jugadores de las categorías del entrenador (Administración: todas)."""
    return (
        ReporteLesion.objects
        .filter(jugador__categoria_actual__in=categorias_visibles(usuario))
        .select_related("jugador", "jugador__categoria_actual", "reportado_por", "revisado_por")
    )
 
 
def crear_reporte_lesion(*, usuario, jugador, tipo, descripcion, fecha_inicio, fecha_fin=None):
    """Guarda el reporte como PENDIENTE. Lanza ValidationError con la lista de errores."""
    errores = []
 
    if jugador is None or not jugadores_que_puede_reportar(usuario).filter(pk=jugador.pk).exists():
        errores.append("Selecciona un jugador vinculado a tu cuenta.")
    if tipo not in ReporteLesion.Tipo.values:
        errores.append("Selecciona el tipo de reporte.")
    if not descripcion:
        errores.append("Describe brevemente la lesión o restricción.")
    elif len(descripcion) > 500:
        errores.append("La descripción no puede superar los 500 caracteres.")
    if not fecha_inicio:
        errores.append("Indica desde qué fecha aplica.")
    elif fecha_fin and fecha_fin < fecha_inicio:
        errores.append("La fecha de término no puede ser anterior a la de inicio.")
 
    if errores:
        raise ValidationError(errores)
 
    reporte = ReporteLesion.objects.create(
        jugador=jugador,
        tipo=tipo,
        descripcion=descripcion,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        reportado_por=usuario,
    )
    # La auditoría no guarda la descripción: es un dato de salud
    registrar_auditoria(
        usuario=usuario,
        accion="LESION_REPORTADA",
        entidad="ReporteLesion",
        entidad_id=reporte.pk,
        detalle={"jugador_id": jugador.pk, "tipo": tipo},
    )
    return reporte


def _sincronizar_alerta_salud_lesion(reporte):
    """
    Crea o reactiva la alerta de salud de un reporte validado.
    """
    if reporte.estado != ReporteLesion.Estado.VALIDADO:
        return None

    fecha_fin = (
        reporte.fecha_fin.strftime("%d/%m/%Y")
        if reporte.fecha_fin
        else "Sin fecha de término"
    )

    descripcion_alerta = (
        f"{reporte.descripcion}\n"
        f"Tipo de reporte: {reporte.get_tipo_display()}\n"
        f"Vigencia: {reporte.fecha_inicio.strftime('%d/%m/%Y')} "
        f"hasta {fecha_fin}"
    )

    return AlertaSalud.objects.update_or_create(
        jugador=reporte.jugador,
        tipo=reporte.get_tipo_display(),
        descripcion=descripcion_alerta,
        defaults={"activa": True},
    )
 
 
@transaction.atomic
def revisar_reporte_lesion(*, usuario, reporte, decision, comentario=""):
    """
    Validación humana del cuerpo técnico.
    No modifica la asistencia ni justifica ausencias automáticamente.
    """
    if not puede_revisar_lesiones(usuario) or not reportes_para_revisar(usuario).filter(pk=reporte.pk).exists():
        raise ValidationError("No tienes permiso para revisar este reporte.")
    if reporte.estado != ReporteLesion.Estado.PENDIENTE:
        raise ValidationError("Este reporte ya fue revisado.")
    if decision not in (ReporteLesion.Estado.VALIDADO, ReporteLesion.Estado.RECHAZADO):
        raise ValidationError("Decisión no válida.")
    if decision == ReporteLesion.Estado.RECHAZADO and not comentario:
        raise ValidationError("Para rechazar un reporte debes indicar el motivo.")
 
    reporte.estado = decision
    reporte.revisado_por = usuario
    reporte.revisado_en = timezone.now()
    reporte.comentario_revision = comentario
    reporte.save(update_fields=["estado", "revisado_por", "revisado_en", "comentario_revision"])

    if decision == ReporteLesion.Estado.VALIDADO:
        _sincronizar_alerta_salud_lesion(reporte)
 
    registrar_auditoria(
        usuario=usuario,
        accion=f"LESION_{decision}",
        entidad="ReporteLesion",
        entidad_id=reporte.pk,
        detalle={"jugador_id": reporte.jugador_id},
    )
    return reporte
 
 
def restricciones_vigentes(jugadores, hoy=None):
    """{jugador_id: reporte} con las lesiones VALIDADAS que siguen vigentes hoy."""
    if hoy is None:
        hoy = timezone.localdate()
 
    vigentes = (
        ReporteLesion.objects
        .filter(
            jugador__in=jugadores,
            estado=ReporteLesion.Estado.VALIDADO,
            fecha_inicio__lte=hoy,
        )
        .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=hoy))
        .order_by("fecha_inicio")
    )
    return {r.jugador_id: r for r in vigentes}
# HU-08 FIN