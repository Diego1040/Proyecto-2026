from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Asistencia, Entrenamiento
from .permisos import categorias_visibles, es_administracion, es_entrenador
from .services import (
    PLAZO_EDICION_HORAS,
    es_entrenamiento_antiguo,
    jugadores_del_entrenamiento,
    puede_modificar,
    registrar_asistencia,
)

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

        # CAMBIO (HU-07): los datos son obligatorios, sin valores inventados
        nombre = request.POST.get("nombre", "").strip()
        fecha = request.POST.get("fecha", "").strip()

        try:
            duracion = int(request.POST.get("duracion", ""))
        except ValueError:
            duracion = 0

        errores = []
        if categoria is None:
            errores.append("Elige una de tus categorías.")
        if not nombre:
            errores.append("Escribe un nombre para el entrenamiento.")
        if not fecha:
            errores.append("Indica la fecha del entrenamiento.")
        if duracion < 1:
            errores.append("La duración debe ser de al menos 1 minuto.")

        if errores:
            for error in errores:
                messages.error(request, error)
            return redirect("deportivo:entrenamientos")
        # FIN CAMBIO

        entrenamiento = Entrenamiento.objects.create(
            categoria=categoria,
            nombre=nombre,
            fecha=fecha,
            duracion=duracion,
            creado_por=usuario,
        )
        return redirect("deportivo:tomar_asistencia", pk=entrenamiento.pk)

    # LISTADO
    lista = (
        Entrenamiento.objects.filter(categoria__in=categorias).select_related("categoria")[:30]
    )

    filas = [
        {
            "entrenamiento": e,
            "registradas": e.asistencias.count(),
            "presentes": e.asistencias.filter(estado=Asistencia.Estado.PRESENTE).count(),
        }
        for e in lista
    ]

    return render(request, "deportivo/entrenamientos.html", {"filas": filas, "categorias": categorias, "hoy": timezone.localdate(), "rol": "Administración" if es_administracion(usuario) else "Entrenador"})

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