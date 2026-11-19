from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import PasswordResetConfirmView, INTERNAL_RESET_SESSION_TOKEN
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Prefetch, Q  # <<< NUEVO (HU-05)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from deportivo.permisos import es_administracion, es_entrenador  # NUEVO (HU-07)
from deportivo.services import resumen_asistencia_mes  # NUEVO (HU-07)
from .forms import (
    ContactoApoderadoForm, InscripcionJugadorForm, RechazoSolicitudForm,
    SolicitudActivacionForm, TelefonoJugadorForm,
)
from .services import (
    inscribir_jugador,
    aprobar_solicitud_inscripcion,
    cambiar_categoria_manual,
    marcar_solicitud_en_revision,
    obtener_categoria_automatica,
    rechazar_solicitud_inscripcion,
    registrar_auditoria,
    completar_activacion,
    cuenta_puede_activarse,
    cuenta_puede_recuperarse,
    solicitar_activacion,
)
from .models import (
    AlertaSalud,
    Apoderado,
    ApoderadoJugador,
    Categoria,
    HistorialCategoria,
    Jugador,
    SolicitudInscripcion,
    Usuario,
)
from .tokens import activacion_token_generator


# =========================================================
# ROLES
# =========================================================



def inicio(request):
    """Portada pública del club."""
    return render(request, "paginas/inicio.html")


@login_required
def panel(request):

    if request.user.groups.filter(
        name="Tesorería"
    ).exists():
        from institucional.permisos import puede_acceder

        if puede_acceder(request.user):
            messages.info(request, format_html(
                'También tienes acceso al área institucional. <a href="{}">Ingresar al área institucional</a>.',
                reverse("institucional:inicio"),
            ))
        return redirect("finanzas:tesoreria")


    """Presenta todos los accesos disponibles sin elegir un perfil exclusivo."""
    usuario = request.user
    # Compatibilidad con el formulario de contacto del panel anterior.
    if request.method == "POST" and request.POST.get("accion") == "contacto":
        return perfil_apoderado(request)
    if request.method == "POST" and request.POST.get("accion") == "inscripcion":
        return redirect("agregar_jugador_apoderado")

    tiene_jugador = hasattr(usuario, "jugador")
    tiene_apoderado = hasattr(usuario, "apoderado")
    administracion = es_administracion(usuario)
    entrenador = es_entrenador(usuario)
    perfiles = []
    if tiene_jugador:
        perfiles.append("Jugador")
    if tiene_apoderado:
        perfiles.append("Apoderado")
    if administracion:
        perfiles.append("Administración")
    if entrenador:
        perfiles.append("Entrenador")
    return render(request, "paginas/panel.html", {
        "perfiles": perfiles,
        "tiene_perfil_jugador": tiene_jugador,
        "tiene_perfil_apoderado": tiene_apoderado,
        "es_administracion": administracion,
        "es_entrenador": entrenador,
    })


@login_required
@require_GET
def panel_jugador(request):
    return redirect("perfil_jugador")


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
            request=request,
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


def activar_cuenta(request):
    if request.method == "POST":
        form = SolicitudActivacionForm(request.POST)
        if form.is_valid():
            solicitar_activacion(
                rut=form.cleaned_data["rut"],
                correo=form.cleaned_data["email"],
                request=request,
            )
            return redirect("activacion_enviada")
    else:
        form = SolicitudActivacionForm()
    return render(request, "registration/activacion_solicitud.html", {"form": form})


class ConfirmarActivacionView(PasswordResetConfirmView):
    template_name = "registration/activacion_confirmar.html"
    token_generator = activacion_token_generator

    def get_user(self, uidb64):
        cuenta = super().get_user(uidb64)
        return cuenta if cuenta_puede_activarse(cuenta) else None

    def form_valid(self, form):
        try:
            completar_activacion(
                cuenta=self.user, formulario=form,
                token=self.request.session.get(INTERNAL_RESET_SESSION_TOKEN),
            )
        except ValidationError:
            self.validlink = False
            return self.render_to_response(self.get_context_data())
        self.request.session.pop(INTERNAL_RESET_SESSION_TOKEN, None)
        return redirect("activacion_completa")


class ConfirmarRecuperacionView(PasswordResetConfirmView):
    def get_user(self, uidb64):
        cuenta = super().get_user(uidb64)
        return cuenta if cuenta_puede_recuperarse(cuenta) else None

    @transaction.atomic
    def form_valid(self, form):
        cuenta = Usuario.objects.select_for_update().get(pk=self.user.pk)
        token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
        if not cuenta_puede_recuperarse(cuenta) or not self.token_generator.check_token(cuenta, token):
            self.validlink = False
            return self.render_to_response(self.get_context_data())
        self.user = cuenta
        form.user = cuenta
        return super().form_valid(form)


@login_required
def perfil_jugador(request):
    try:
        jugador_vinculado = request.user.jugador
    except Jugador.DoesNotExist:
        messages.error(
            request,
            "Tu cuenta no tiene un perfil de jugador asociado.",
        )
        return redirect("panel")

    jugador = (
        Jugador.objects
        .select_related("categoria_actual")
        .prefetch_related(
            Prefetch(
                "alertas_salud",
                queryset=(
                    AlertaSalud.objects
                    .filter(activa=True)
                    .order_by("tipo")
                ),
                to_attr="alertas_activas",
            ),
            Prefetch(
                "historial_categorias",
                queryset=(
                    HistorialCategoria.objects
                    .select_related(
                        "categoria_anterior",
                        "categoria_nueva",
                        "cambiado_por",
                    )
                    .order_by("-fecha")
                ),
                to_attr="historial_categorias_cargado",
            ),
        )
        .get(pk=jugador_vinculado.pk)
    )

    if request.method == "POST":
        telefono_form = TelefonoJugadorForm(
            request.POST,
            instance=jugador,
        )

        if telefono_form.is_valid():
            jugador_actualizado = telefono_form.save(commit=False)
            jugador_actualizado.save(
                update_fields=("telefono", "updated_at"),
            )
            messages.success(
                request,
                "Tu teléfono fue actualizado correctamente.",
            )
            return redirect("perfil_jugador")
    else:
        telefono_form = TelefonoJugadorForm(instance=jugador)

    jugador.asistencia_mes = resumen_asistencia_mes(jugador)

    return render(
        request,
        "usuarios/perfil_jugador.html",
        {
            "jugador": jugador,
            "telefono_form": telefono_form,
        },
    )


@login_required
def perfil_apoderado(request):
    try:
        apoderado = request.user.apoderado
    except Apoderado.DoesNotExist:
        messages.error(
            request,
            "Tu cuenta no tiene un perfil de apoderado asociado.",
        )
        return redirect("panel")

    contacto_form = ContactoApoderadoForm(
        request.POST if request.method == "POST" else None,
        instance=apoderado,
    )
    if request.method == "POST" and contacto_form.is_valid():
        with transaction.atomic():
            jugador = Jugador.objects.select_for_update().filter(usuario=request.user).first()
            usuario = Usuario.objects.select_for_update().get(pk=request.user.pk)
            correo_anterior = usuario.email
            apoderado = contacto_form.save(commit=False)
            apoderado.save(update_fields=["telefono", "email", "updated_at"])
            usuario.email = apoderado.email
            usuario.save(update_fields=["email"])
            if (
                jugador is not None and correo_anterior
                and jugador.email.casefold() == correo_anterior.casefold()
            ):
                jugador.email = usuario.email
                jugador.save(update_fields=["email"])
        messages.success(request, "Tus datos de contacto fueron actualizados correctamente.")
        return redirect("panel" if request.resolver_match.url_name == "panel" else "perfil_apoderado")

    vinculos = (
        ApoderadoJugador.objects
        .filter(
            apoderado=apoderado,
            activo=True,
        )
        .select_related(
            "jugador",
            "jugador__categoria_actual",
        )
        .prefetch_related(
            Prefetch(
                "jugador__solicitudes_inscripcion",
                queryset=(
                    SolicitudInscripcion.objects
                    .order_by("-fecha_solicitud")
                ),
                to_attr="solicitudes_ordenadas",
            ),
        )
        .order_by(
            "-es_principal",
            "jugador__apellidos",
            "jugador__nombres",
        )
    )

    for vinculo in vinculos:
        vinculo.jugador.asistencia_mes = resumen_asistencia_mes(vinculo.jugador)

    return render(
        request,
        "usuarios/perfil_apoderado.html",
        {
            "apoderado": apoderado,
            "contacto_form": contacto_form,
            "vinculos": vinculos,
        },
    )
