from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import PasswordResetConfirmView, INTERNAL_RESET_SESSION_TOKEN
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import render, redirect, get_object_or_404

from django.views.decorators.http import require_POST

from .forms import (
    CorreoApoderadoForm,
    InscripcionJugadorForm,
    RechazoSolicitudForm,
    SolicitudActivacionForm,
    TelefonoApoderadoForm,
    TelefonoJugadorForm,
)
from .models import (
    AlertaSalud,
    Apoderado,
    ApoderadoJugador,
    HistorialCategoria,
    Jugador,
    SolicitudInscripcion,
    Usuario,
)
from .services import (
    aprobar_solicitud_inscripcion,
    completar_activacion,
    cuenta_puede_activarse,
    cuenta_puede_recuperarse,
    crear_solicitud_inscripcion,
    marcar_solicitud_en_revision,
    rechazar_solicitud_inscripcion,
    solicitar_activacion,
)
from .tokens import activacion_token_generator


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
            email=(datos.get("email") or "").strip(),
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
                email=(datos["email_apoderado"]).strip(),
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
    if request.user.is_authenticated:
        return redirect("panel")

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
            completar_activacion(cuenta=self.user, formulario=form)
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
def panel(request):
    """Entrada general que presenta los accesos disponibles."""
    usuario = request.user

    tiene_perfil_jugador = hasattr(usuario, "jugador")
    tiene_perfil_apoderado = hasattr(usuario, "apoderado")

    perfiles = []

    if usuario.is_staff:
        perfiles.append("Administración")

    if tiene_perfil_apoderado:
        perfiles.append("Apoderado")

    if tiene_perfil_jugador:
        perfiles.append("Jugador")

    return render(
        request,
        "paginas/panel.html",
        {
            "perfiles": perfiles,
            "tiene_perfil_jugador": tiene_perfil_jugador,
            "tiene_perfil_apoderado": tiene_perfil_apoderado,
            "es_administracion": usuario.is_staff,
        },
    )


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

    if request.method == "POST" and request.POST.get("accion") == "guardar_correo":
        correo_form = CorreoApoderadoForm(
            request.POST,
            instance=apoderado,
            usuario=request.user,
        )
        telefono_form = TelefonoApoderadoForm(instance=apoderado)
        if correo_form.is_valid():
            apoderado_actualizado = correo_form.save(commit=False)
            apoderado_actualizado.save(update_fields=("email", "updated_at"))
            messages.success(request, "Tu correo de contacto fue actualizado.")
            return redirect("perfil_apoderado")
    elif request.method == "POST":
        telefono_form = TelefonoApoderadoForm(
            request.POST,
            instance=apoderado,
        )
        correo_form = CorreoApoderadoForm(instance=apoderado, usuario=request.user)

        if telefono_form.is_valid():
            apoderado_actualizado = telefono_form.save(commit=False)
            apoderado_actualizado.save(
                update_fields=("telefono", "updated_at"),
            )
            messages.success(
                request,
                "Tu teléfono fue actualizado correctamente.",
            )
            return redirect("perfil_apoderado")
    else:
        telefono_form = TelefonoApoderadoForm(instance=apoderado)
        correo_form = CorreoApoderadoForm(instance=apoderado, usuario=request.user)

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

    return render(
        request,
        "usuarios/perfil_apoderado.html",
        {
            "apoderado": apoderado,
            "telefono_form": telefono_form,
            "correo_form": correo_form,
            "vinculos": vinculos,
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
                _crear_inscripcion_desde_form(
                    form=form,
                    solicitante=request.user,
                    apoderado_existente=apoderado,
                )
            except ValidationError as exc:
                _agregar_error_validacion(form, exc)
            else:
                messages.success(
                    request,
                    "La solicitud fue enviada correctamente.",
                )
                return redirect("perfil_apoderado")
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
            request=request,
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
