from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404

from django.views.decorators.http import require_POST

from .forms import InscripcionJugadorForm, RechazoSolicitudForm
from .models import Jugador, Apoderado, ApoderadoJugador, AlertaSalud, SolicitudInscripcion
from .services import crear_solicitud_inscripcion, aprobar_solicitud_inscripcion, rechazar_solicitud_inscripcion, marcar_solicitud_en_revision


def _agregar_error_validacion(form, exc):
    if hasattr(exc, "message_dict"):
        for campo, mensajes in exc.message_dict.items():
            destino = campo if campo in form.fields else None

            for mensaje in mensajes:
                form.add_error(destino, mensaje,)
        return

    for mensaje in exc.messages:
        form.add_error(None, mensaje,)

def _crear_inscripcion_desde_form(*,form, solicitante=None, apoderado_existente=None,):
    datos = form.cleaned_data
    edad = datos["edad_calculada"]

    with transaction.atomic():
        jugador = Jugador(
            rut=datos["rut"],
            nombres=datos["nombres"].strip(),
            apellidos=datos["apellidos"].strip(),
            fecha_nacimiento=datos["fecha_nacimiento"],
            rama=datos["rama"],
            telefono=(datos.get("telefono") or "").strip(),
            nombre_contacto_emergencia=(datos.get("nombre_contacto_emergencia")or "").strip(),
            telefono_contacto_emergencia=(datos.get("telefono_contacto_emergencia")or "").strip(),
            procedencia=datos["procedencia"],
            club_anterior=(datos.get("club_anterior") or "").strip(),
            peso_kg=datos.get("peso_kg"),
            talla_cm=datos.get("talla_cm"),
        )

        jugador.full_clean()
        jugador.save()

        apoderado = apoderado_existente

        if edad < 18 and apoderado is None:
            apoderado = Apoderado(
                rut=datos["rut_apoderado"],
                nombres=(datos["nombres_apoderado"]).strip(),
                apellidos=(datos["apellidos_apoderado"]).strip(),
                telefono=(datos["telefono_apoderado"]).strip(),
            )

            apoderado.full_clean()
            apoderado.save()

        if apoderado is not None:
            vinculo = ApoderadoJugador(
                apoderado=apoderado,
                jugador=jugador,
                parentesco=(datos.get("parentesco") or "").strip(),
                es_principal=True,
                puede_gestionar=True,
                activo=True,
            )

            vinculo.full_clean()
            vinculo.save()

        alerta_tipo = (datos.get("alerta_tipo") or "").strip()

        alerta_descripcion = (datos.get("alerta_descripcion") or "").strip()

        if alerta_tipo and alerta_descripcion:
            alerta = AlertaSalud(jugador=jugador,tipo=alerta_tipo,descripcion=alerta_descripcion,)

            alerta.full_clean()
            alerta.save()

        solicitud = crear_solicitud_inscripcion(
            jugador=jugador,
            solicitante=solicitante,
            consentimiento=datos["consentimiento"],
            observaciones=(datos.get("observaciones") or "").strip(),
        )

        return solicitud

def _es_personal_administrativo(usuario):
    return (
        usuario.is_authenticated and usuario.is_staff
    )

def inscripcion_publica(request):
    if request.method == "POST":
        form = InscripcionJugadorForm(request.POST)

        if form.is_valid():
            try:
                solicitud = _crear_inscripcion_desde_form(
                    form=form,
                    solicitante=(
                        request.user
                        if request.user.is_authenticated
                        else None
                    ),
                )
            except ValidationError as exc:
                _agregar_error_validacion(form,exc,)
            else:
                request.session["ultima_solicitud_id"] = solicitud.pk

                messages.success(request,"La solicitud fue enviada correctamente.",)

                return redirect("inscripcion_exito")
    else:
        form = InscripcionJugadorForm()

    return render(
        request,
        "usuarios/inscripcion_form.html",
        {
            "form": form,
            "modo_apoderado": False,
        },
    )

def inscripcion_exito(request):
    solicitud_id = request.session.pop("ultima_solicitud_id",None,)

    return render(
        request,
        "usuarios/inscripcion_exito.html",
        {
            "solicitud_id": solicitud_id,
        },
    )

def inicio(request):
    """Portada publica del club."""
    return render(request, "paginas/inicio.html")


@login_required
def panel(request):
    """
    Destino provisional despues del login.

    Cuando existan las vistas por rol (apoderado, entrenador,
    tesoreria, administracion) esta vista debe redirigir a la
    que corresponda segun el perfil del usuario.
    """
    usuario = request.user

    if usuario.is_staff:
        perfil = "Administracion"
    elif hasattr(usuario, "apoderado"):
        perfil = "Apoderado"
    elif hasattr(usuario, "jugador"):
        perfil = "Jugador"
    else:
        perfil = "Sin perfil asignado"

    return render(request, "paginas/panel.html", {"perfil": perfil})

@user_passes_test(
    _es_personal_administrativo,
    login_url="login",
)
def solicitudes_administracion(request):
    estado = request.GET.get("estado", "").strip()

    solicitudes = (
        SolicitudInscripcion.objects
        .select_related(
            "jugador",
            "jugador__categoria_actual",
            "revisado_por",
        )
        .order_by("-fecha_solicitud")
    )

    estados_validos = {
        valor
        for valor, _ in SolicitudInscripcion.Estado.choices
    }

    if estado in estados_validos:
        solicitudes = solicitudes.filter(
            estado=estado
        )

    return render(
        request,
        "usuarios/solicitudes_lista.html",
        {
            "solicitudes": solicitudes,
            "estado_actual": estado,
            "estados": SolicitudInscripcion.Estado.choices,
        },
    )

@user_passes_test(_es_personal_administrativo, login_url="login",)
def solicitud_detalle(request, pk):
    solicitud = get_object_or_404(
        SolicitudInscripcion.objects
        .select_related(
            "jugador",
            "jugador__categoria_actual",
            "solicitante",
            "revisado_por",
        )
        .prefetch_related(
            "jugador__vinculos_apoderados__apoderado",
            "jugador__alertas_salud",
        ),
        pk=pk,
    )

    rechazo_form = RechazoSolicitudForm()

    return render(
        request,
        "usuarios/solicitud_detalle.html",
        {
            "solicitud": solicitud,
            "rechazo_form": rechazo_form,
        },
    )

@require_POST
@user_passes_test(_es_personal_administrativo, login_url="login",)
def solicitud_iniciar_revision(request, pk):
    solicitud = get_object_or_404(
        SolicitudInscripcion,
        pk=pk,
    )

    try:
        marcar_solicitud_en_revision(solicitud=solicitud)
    except ValidationError as exc:
        messages.error(
            request,
            " ".join(exc.messages),
        )
    else:
        messages.success(request, "La solicitud pasó a revisión.",)

    return redirect(
        "solicitud_detalle",
        pk=pk,
    )

@require_POST
@user_passes_test(_es_personal_administrativo, login_url="login",)
def solicitud_aprobar(request, pk):
    solicitud = get_object_or_404(
        SolicitudInscripcion,
        pk=pk,
    )

    try:
        aprobar_solicitud_inscripcion(
            solicitud=solicitud,
            usuario=request.user,
        )
    except ValidationError as exc:
        messages.error(
            request,
            " ".join(exc.messages),
        )
    else:
        messages.success(
            request,
            "Solicitud aprobada correctamente.",
        )

    return redirect(
        "solicitud_detalle",
        pk=pk,
    )

@require_POST
@user_passes_test(_es_personal_administrativo, login_url="login",)
def solicitud_rechazar(request, pk):
    solicitud = get_object_or_404(
        SolicitudInscripcion,
        pk=pk,
    )

    form = RechazoSolicitudForm(
        request.POST
    )

    if form.is_valid():
        try:
            rechazar_solicitud_inscripcion(
                solicitud=solicitud,
                usuario=request.user,
                motivo=form.cleaned_data["motivo"],
            )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages),
            )
        else:
            messages.success(
                request,
                "Solicitud rechazada.",
            )
    else:
        messages.error(
            request,
            "Debe indicar un motivo válido para rechazar.",
        )

    return redirect(
        "solicitud_detalle",
        pk=pk,
    )