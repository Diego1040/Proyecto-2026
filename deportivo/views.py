from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth import get_user_model  #HU-06
from django.utils import timezone
from datetime import date as _date, time as _time

from django.views.decorators.http import require_POST

from .models import Asistencia, Entrenamiento, Evento
from .permisos import categorias_visibles, es_administracion, es_entrenador
from .services import (
    categorias_del_usuario,
    eventos_visibles,
    puede_eliminar_evento,
    puede_publicar_eventos,
    validar_evento,
    PLAZO_EDICION_HORAS,
    actualizar_planificacion,          #HU-06
    es_entrenamiento_antiguo,
    historial_planificacion,           #HU-06
    jugadores_del_entrenamiento,
    puede_editar_planificacion,        #HU-06
    puede_modificar,
    registrar_asistencia,
    responsables_posibles,             #HU-06
    validar_planificacion,             #HU-06
)
from usuarios.services import registrar_auditoria  # HU-06

# Create your views here.
def _sin_permiso(request):
    messages.error(request, "No tiene permiso para ver registrar asistencia.")
    return redirect("panel")

@login_required
def entrenamientos(request):
    """Lista de entrenamientos y formulario para crear uno nuevo."""
    usuario = request.user

    if not (es_entrenador(usuario) or es_administracion(usuario)):
        return _sin_permiso(request)

    categorias = categorias_visibles(usuario)

    # CREAR ENTRENAMIENTO

    if request.method == "POST":
        categoria = categorias.filter(pk=request.POST.get("categoria_id")).first()

        #HU-06
        datos = _leer_planificacion(request.POST)
        errores = validar_planificacion(categoria=categoria, **datos)

        if errores:
            for error in errores:
                messages.error(request, error)
            return redirect("deportivo:entrenamientos")

        entrenamiento = Entrenamiento.objects.create(
            categoria=categoria,
            creado_por=usuario,
            **datos,
        )

        registrar_auditoria(
            usuario=usuario,
            accion="PLANIFICACION_CREADA",
            entidad="Entrenamiento",
            entidad_id=entrenamiento.pk,
            detalle={"nombre": entrenamiento.nombre, "fecha": str(entrenamiento.fecha)},
        )

        messages.success(request, f"Entrenamiento \"{entrenamiento.nombre}\" planificado.")
        return redirect("deportivo:entrenamientos")
        # FIN CAMBIO

    # LISTADO
    lista = (
        Entrenamiento.objects.filter(categoria__in=categorias).select_related("categoria", "responsable")[:30]
    )

    hoy = timezone.localdate()

    #HU-06
    proximos = (
        Entrenamiento.objects
        .filter(categoria__in=categorias, fecha__gte=hoy)
        .select_related("categoria", "responsable")
        .order_by("fecha", "hora_inicio")
    )

    filas = [
        {
            "entrenamiento": e,
            "registradas": e.asistencias.count(),
            "presentes": e.asistencias.filter(estado=Asistencia.Estado.PRESENTE).count(),
        }
        for e in lista
        if e.fecha < hoy
    ]

    # Entrenadores de las categorias visibles (el servidor revisa
    # despues que el elegido sea de la categoria del entrenamiento)
    responsables = (
        get_user_model().objects
        .filter(
            is_active=True,
            groups__name="Entrenador",
            perfil_entrenador__categorias__in=categorias,
        )
        .distinct()
        .order_by("first_name", "last_name", "rut")
    )

    return render(request, "deportivo/entrenamientos.html", {"filas": filas, "proximos": proximos, "responsables": responsables, "categorias": categorias, "hoy": hoy, "rol": "Administración" if es_administracion(usuario) else "Entrenador"})

@login_required
def tomar_asistencia(request, pk):
    """Pasar lista de un entrenamiento (pensado para celular)"""
    usuario = request.user

    if not (es_entrenador(request.user) or es_administracion(request.user)):
        return _sin_permiso(request)

    entrenamiento = get_object_or_404(Entrenamiento.objects.select_related("categoria"), pk=pk, categoria__in=categorias_visibles(usuario))

    # GUARDAR ASISTENCIA
    if request.method == "POST":
        estados = {}
        for clave, valor in request.POST.items():
            if clave.startswith("estado_"):
                try:
                    estados[int(clave.removeprefix("estado_"))] = valor
                except ValueError:
                    continue

        try:
            guardadas = registrar_asistencia(entrenamiento = entrenamiento, usuario = usuario, estados=estados, motivo=request.POST.get("motivo", ""),)
            messages.success(request, f"Asistencia guardada ({guardadas} jugadores).")
            return redirect("deportivo:entrenamientos")

        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("deportivo:tomar_asistencia", pk=pk)

    registradas = {
        a.jugador_id: a
        for a in entrenamiento.asistencias.select_related("registrado_por")
    }

    filas = [
        {
            "jugador": j,
            "estado": registradas[j.pk].estado if j.pk in registradas else "PRESENTE",
            "registro": registradas.get(j.pk),
        }
        for j in jugadores_del_entrenamiento(entrenamiento)
    ]

    return render(request, "deportivo/tomar_asistencia.html",
        {
            "entrenamiento": entrenamiento,
            "filas": filas,
            "estados": Asistencia.Estado.choices,
            "antiguo": es_entrenamiento_antiguo(entrenamiento),
            "puede_modificar": puede_modificar(usuario, entrenamiento),
            "plazo_horas": PLAZO_EDICION_HORAS,
            "rol": "Administración" if es_administracion(usuario) else "Entrenador",
        },
    )


#HU-06
def _leer_planificacion(post):
    """Lee los campos de la planificacion desde el formulario."""
    try:
        duracion = int(post.get("duracion", ""))
    except ValueError:
        duracion = 0

    responsable = (
        get_user_model().objects.filter(pk=post.get("responsable_id")).first()
        if post.get("responsable_id") else None
    )

    return {
        "nombre": post.get("nombre", "").strip(),
        "fecha": post.get("fecha", "").strip(),
        "hora_inicio": post.get("hora_inicio", "").strip(),
        "duracion": duracion,
        "objetivo": post.get("objetivo", "").strip(),
        "responsable": responsable,
    }


@login_required
def editar_planificacion(request, pk):
    """Modificar la planificacion de un entrenamiento y ver su historial."""
    usuario = request.user

    if not (es_entrenador(usuario) or es_administracion(usuario)):
        return _sin_permiso(request)

    entrenamiento = get_object_or_404(
        Entrenamiento.objects.select_related("categoria", "responsable"),
        pk=pk,
        categoria__in=categorias_visibles(usuario),
    )
    puede_editar = puede_editar_planificacion(usuario, entrenamiento)

    if request.method == "POST":
        datos = _leer_planificacion(request.POST)
        errores = validar_planificacion(categoria=entrenamiento.categoria, **datos)

        if errores:
            for error in errores:
                messages.error(request, error)
            return redirect("deportivo:editar_planificacion", pk=pk)

        try:
            cambios = actualizar_planificacion(
                entrenamiento=entrenamiento,
                usuario=usuario,
                datos=datos,
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("deportivo:editar_planificacion", pk=pk)

        if cambios:
            messages.success(request, "Planificación actualizada. El cambio quedó en el historial.")
        else:
            messages.success(request, "No había cambios que guardar.")
        return redirect("deportivo:editar_planificacion", pk=pk)

    return render(request, "deportivo/editar_planificacion.html", {
        "entrenamiento": entrenamiento,
        "responsables": responsables_posibles(entrenamiento.categoria),
        "historial": historial_planificacion(entrenamiento),
        "puede_editar": puede_editar,
        "rol": "Administración" if es_administracion(usuario) else "Entrenador",
    })

def _leer_fecha(texto):
    try:
        return _date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def _leer_hora(texto):
    try:
        return _time.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


@login_required
def calendario(request):
    """Calendario deportivo: todos lo consultan, Administración y entrenadores publican."""
    usuario = request.user
    publicar = puede_publicar_eventos(usuario)

    # PUBLICAR EVENTO
    if request.method == "POST":
        if not publicar:
            messages.error(request, "No tienes permiso para publicar eventos.")
            return redirect("deportivo:calendario")

        categoria_pedida = request.POST.get("categoria_id", "")
        categoria = None
        if categoria_pedida:
            categoria = categorias_visibles(usuario).filter(pk=categoria_pedida).first()

        datos = {
            "tipo": request.POST.get("tipo", ""),
            "titulo": request.POST.get("titulo", "").strip(),
            "fecha": _leer_fecha(request.POST.get("fecha")),
            "hora": _leer_hora(request.POST.get("hora")),
            "lugar": request.POST.get("lugar", "").strip(),
        }
        errores = validar_evento(
            usuario=usuario,
            categoria=categoria,
            categoria_pedida=categoria_pedida,
            **datos,
        )
        if errores:
            for error in errores:
                messages.error(request, error)
            return redirect("deportivo:calendario")

        evento = Evento.objects.create(
            categoria=categoria,
            descripcion=request.POST.get("descripcion", "").strip(),
            creado_por=usuario,
            **datos,
        )
        registrar_auditoria(
            usuario=usuario,
            accion="EVENTO_CREADO",
            entidad="Evento",
            entidad_id=evento.pk,
            detalle={"titulo": evento.titulo, "fecha": str(evento.fecha)},
        )
        messages.success(request, f"Evento \"{evento.titulo}\" publicado.")
        return redirect("deportivo:calendario")

    # CONSULTAR (con filtro por categoría)
    mis_categorias = categorias_del_usuario(usuario)
    filtro = mis_categorias.filter(pk=request.GET.get("categoria") or None).first()

    eventos = eventos_visibles(usuario, categoria=filtro, desde=timezone.localdate())
    for evento in eventos:
        evento.se_puede_eliminar = publicar and puede_eliminar_evento(usuario, evento)

    return render(request, "deportivo/calendario.html", {
        "eventos": eventos,
        "mis_categorias": mis_categorias,
        "filtro": filtro,
        "puede_publicar": publicar,
        "categorias_publicar": categorias_visibles(usuario) if publicar else [],
        "es_admin": es_administracion(usuario),
        "tipos": Evento.Tipo.choices,
        "hoy": timezone.localdate(),
    })


@login_required
@require_POST
def eliminar_evento(request, pk):
    evento = get_object_or_404(Evento, pk=pk)
    if not (puede_publicar_eventos(request.user) and puede_eliminar_evento(request.user, evento)):
        messages.error(request, "No tienes permiso para eliminar este evento.")
        return redirect("deportivo:calendario")

    registrar_auditoria(
        usuario=request.user,
        accion="EVENTO_ELIMINADO",
        entidad="Evento",
        entidad_id=evento.pk,
        detalle={"titulo": evento.titulo, "fecha": str(evento.fecha)},
    )
    evento.delete()
    messages.success(request, "Evento eliminado.")
    return redirect("deportivo:calendario")