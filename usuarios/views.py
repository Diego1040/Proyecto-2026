from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q  # <<< NUEVO (HU-05)
from django.shortcuts import get_object_or_404, redirect, render
from deportivo.permisos import es_administracion, es_entrenador  # NUEVO (HU-07)
from deportivo.services import resumen_asistencia_mes  # NUEVO (HU-07)
from .forms import InscripcionJugadorForm, RechazoSolicitudForm
from .services import (
    inscribir_jugador,
    aprobar_solicitud_inscripcion,
    cambiar_categoria_manual,          
    marcar_solicitud_en_revision,
    obtener_categoria_automatica,      
    rechazar_solicitud_inscripcion,
    registrar_auditoria,               
)
from .models import (
    Apoderado,
    ApoderadoJugador,
    Categoria,                         
    HistorialCategoria,               
    Jugador,
    SolicitudInscripcion,
)


# =========================================================
# ROLES
# =========================================================



def inicio(request):
    """Portada pública del club."""
    return render(request, "paginas/inicio.html")


def obtener_jugador_adulto(usuario):
    """
    Devuelve el jugador asociado a la cuenta cuando tiene 18 años o más.
    Si la cuenta no está asociada a un jugador adulto, devuelve None.
    """
    jugador = getattr(usuario, "jugador", None)

    if (
        jugador is not None
        and jugador.edad is not None
        and jugador.edad >= 18
    ):
        return jugador

    return None

@login_required
def panel(request):
    usuario = request.user

    # ==========================================================
    # JUGADOR ADULTO
    # ==========================================================
    jugador_adulto = obtener_jugador_adulto(usuario)

    if jugador_adulto is not None:

        return redirect("panel_jugador")

    if hasattr(usuario, "apoderado"):

        apoderado = usuario.apoderado

        # -------------------------------------------------
        # GUARDAR DATOS DE CONTACTO
        # -------------------------------------------------
        if (
            request.method == "POST"
            and request.POST.get("accion") == "contacto"
        ):

            telefono = request.POST.get("telefono", "").strip()
            email = request.POST.get("email", "").strip()

            with transaction.atomic():
                apoderado.telefono = telefono
                apoderado.email = email
                apoderado.save(update_fields=["telefono", "email", "updated_at"])

                usuario.email = email
                usuario.save(update_fields=["email"])

            messages.success(
                request,
                "Tus datos de contacto fueron actualizados correctamente."
            )

            return redirect("panel")

        if request.method == "POST" and request.POST.get("accion") == "inscripcion":
            return redirect("agregar_jugador_apoderado")

        # -------------------------------------------------
        # OBTENER TODOS LOS JUGADORES DEL APODERADO
        # -------------------------------------------------
        vinculos = (
            apoderado.vinculos_jugadores
            .filter(activo=True)
            .select_related("jugador", "jugador__categoria_actual")
            .order_by("-es_principal", "-created_at")
        )

        jugadores = [vinculo.jugador for vinculo in vinculos]

        # Ultima solicitud de cada jugador, para mostrar si fue
        # rechazada y el motivo (HU-03)
        for jugador in jugadores:
            jugador.ultima_solicitud = (
                jugador.solicitudes_inscripcion
                .order_by("-fecha_solicitud")
                .first()
            )

            jugador.asistencia_mes = resumen_asistencia_mes(jugador)

        # -------------------------------------------------
        # RENDER DEL PANEL
        # -------------------------------------------------
        return render(
            request,
            "usuarios/panel_apoderado.html",
            {
                "perfil": "Apoderado",
                "apoderado": apoderado,
                "jugadores": jugadores,
            },
        )

    # =====================================================
    # ADMINISTRACIÓN DEL CLUB (HU-03)
    # =====================================================
    if es_administracion(usuario):
        return redirect("validar_fichas")

    if es_entrenador(usuario):
        return redirect("deportivo:entrenamientos")

    # =====================================================
    # ADMINISTRACIÓN (superusuario / staff de Django)
    # =====================================================
    if usuario.is_staff:

        return render(
            request,
            "paginas/panel.html",
            {
                "perfil": "Administración",
            },
        )

    # =====================================================
    # OTROS USUARIOS
    # =====================================================
    return render(
        request,
        "paginas/panel.html",
        {
            "perfil": "Jugador",
        },
    )


# =========================================================
# HU-03 · VALIDACIÓN DE FICHAS
# =========================================================
@login_required
@require_GET
def validar_fichas(request):
    if not es_administracion(request.user):
        messages.error(request, "No tienes permiso para revisar solicitudes.")
        return redirect("panel")
    return redirect("solicitudes_administracion")



@login_required
def panel_jugador(request):
    """Portal personal para jugadores mayores de edad."""

    usuario = request.user
    jugador = obtener_jugador_adulto(usuario)

    # Si la cuenta no corresponde a un jugador adulto,
    # vuelve al panel normal.
    if jugador is None:
        return redirect("panel")

    # ==========================================================
    # ACTUALIZAR DATOS PERSONALES
    # ==========================================================
    if (
        request.method == "POST"
        and request.POST.get("accion") == "datos"
    ):
        telefono = request.POST.get("telefono", "").strip()
        email = request.POST.get("email", "").strip()

        jugador.telefono = telefono
        jugador.save(update_fields=["telefono"])

        usuario.email = email
        usuario.save(update_fields=["email"])

        messages.success(
            request,
            "Tus datos fueron actualizados correctamente.",
        )

        return redirect("panel_jugador")

    return render(
        request,
        "usuarios/panel_jugador.html",
        {
            "perfil": "Jugador",
            "jugador": jugador,
        },
    )




@login_required
def categorias_jugadores(request):

    usuario = request.user

    if not es_administracion(usuario):
        messages.error(
            request,
            "No tienes permiso para cambiar categorías."
        )
        return redirect("panel")

    # -----------------------------------------------------
    # REGISTRAR EXCEPCION MANUAL
    # -----------------------------------------------------
    if request.method == "POST":

        jugador = get_object_or_404(
            Jugador,
            pk=request.POST.get("jugador_id"),
        )
        nueva_categoria = get_object_or_404(
            Categoria,
            pk=request.POST.get("categoria_id"),
            activa=True,
        )
        motivo = request.POST.get("motivo", "")

        categoria_anterior = jugador.categoria_actual

        try:
            with transaction.atomic():
                cambiar_categoria_manual(
                    jugador,
                    nueva_categoria,
                    usuario,
                    motivo,
                )
                registrar_auditoria(
                    usuario=usuario,
                    accion="CATEGORIA_EXCEPCION_MANUAL",
                    entidad="Jugador",
                    entidad_id=jugador.pk,
                    detalle={
                        "categoria_anterior": (
                            str(categoria_anterior)
                            if categoria_anterior else None
                        ),
                        "categoria_nueva": str(nueva_categoria),
                        "motivo": motivo.strip(),
                    },
                )

            messages.success(
                request,
                f"{jugador.nombres} {jugador.apellidos} quedó en "
                f"{nueva_categoria} (excepción manual)."
            )

        except ValidationError as error:
            messages.error(request, " ".join(error.messages))

        return redirect("categorias_jugadores")

    # -----------------------------------------------------
    # LISTADO DE JUGADORES
    # -----------------------------------------------------
    busqueda = request.GET.get("q", "").strip()

    jugadores = (
        Jugador.objects
        .exclude(estado=Jugador.Estado.INACTIVO)
        .select_related("categoria_actual")
        .prefetch_related("historial_categorias")
        .order_by("apellidos", "nombres")
    )

    if busqueda:
        jugadores = jugadores.filter(
            Q(nombres__icontains=busqueda)
            | Q(apellidos__icontains=busqueda)
            | Q(rut__icontains=busqueda)
        )

    filas = []

    for jugador in jugadores:

        try:
            calculada = obtener_categoria_automatica(
                fecha_nacimiento=jugador.fecha_nacimiento,
                rama=jugador.rama,
            )
        except ValidationError:
            calculada = None

        historial = list(jugador.historial_categorias.all())
        ultimo = historial[0] if historial else None

        filas.append({
            "jugador": jugador,
            "calculada": calculada,
            "es_excepcion": (
                ultimo is not None
                and ultimo.tipo_cambio
                == HistorialCategoria.TipoCambio.EXCEPCION_MANUAL
            ),
            "motivo_excepcion": ultimo.motivo if ultimo else "",
        })

    categorias = Categoria.objects.filter(activa=True).order_by("orden")

    cambios_recientes = (
        HistorialCategoria.objects
        .filter(tipo_cambio=HistorialCategoria.TipoCambio.EXCEPCION_MANUAL)
        .select_related(
            "jugador",
            "categoria_anterior",
            "categoria_nueva",
            "cambiado_por",
        )
        .order_by("-fecha")[:10]
    )

    return render(
        request,
        "usuarios/categorias_jugadores.html",
        {
            "filas": filas,
            "categorias": categorias,
            "cambios_recientes": cambios_recientes,
            "busqueda": busqueda,
        },
    )

def _agregar_error_validacion(form, exc):
    if isinstance(exc, IntegrityError):
        form.add_error(None, "No es posible completar la inscripción. Solicita revisión administrativa.")
        return
    if hasattr(exc, "message_dict"):
        for campo, mensajes in exc.message_dict.items():
            destino = campo if campo in form.fields else None

            for mensaje in mensajes:
                form.add_error(destino, mensaje,)
        return

    for mensaje in exc.messages:
        form.add_error(None, mensaje,)


def inscripcion_publica(request):
    if request.user.is_authenticated:
        return redirect("panel")

    if request.method == "POST":
        form = InscripcionJugadorForm(request.POST)

        if form.is_valid():
            try:
                solicitud = inscribir_jugador(
                    datos=form.cleaned_data,
                )
            except (ValidationError, IntegrityError) as exc:
                _agregar_error_validacion(form, exc)
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


@login_required
def agregar_jugador_apoderado(request):
    try:
        apoderado = request.user.apoderado
    except Apoderado.DoesNotExist:
        messages.error(
            request,
            "Necesitas un perfil de apoderado para agregar jugadores.",
        )
        return redirect("panel")

    if request.method == "POST":
        form = InscripcionJugadorForm(
            request.POST,
            apoderado_existente=apoderado,
        )

        if form.is_valid():
            try:
                inscribir_jugador(
                    datos=form.cleaned_data,
                    solicitante=request.user,
                    apoderado_existente=apoderado,
                )
            except (ValidationError, IntegrityError) as exc:
                _agregar_error_validacion(form, exc)
            else:
                messages.success(
                    request,
                    "La solicitud fue enviada correctamente.",
                )
                return redirect("panel")
    else:
        form = InscripcionJugadorForm(
            apoderado_existente=apoderado,
        )

    return render(
        request,
        "usuarios/inscripcion_form.html",
        {
            "form": form,
            "modo_apoderado": True,
        },
    )


@user_passes_test(
    es_administracion,
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


@user_passes_test(es_administracion, login_url="login",)
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
@user_passes_test(es_administracion, login_url="login",)
def solicitud_iniciar_revision(request, pk):
    solicitud = get_object_or_404(
        SolicitudInscripcion,
        pk=pk,
    )

    try:
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=request.user)
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
@user_passes_test(es_administracion, login_url="login",)
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
    except IntegrityError:
        messages.error(request, "No fue posible preparar la cuenta. Solicita revisión de identidad.")
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
@user_passes_test(es_administracion, login_url="login",)
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
