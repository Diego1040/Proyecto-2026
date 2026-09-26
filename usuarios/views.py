from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms import InscripcionForm
from .services import (
    asignar_categoria_automatica,
    aprobar_solicitud_inscripcion,
    marcar_solicitud_en_revision,
    rechazar_solicitud_inscripcion,
)
from .models import (
    ApoderadoJugador,
    Jugador,
    SolicitudInscripcion,
)


# =========================================================
# ROLES
# =========================================================
def es_administracion(usuario):
    """
    Indica si el usuario pertenece al rol Administracion del club.

    Por ahora el rol se maneja con el grupo de Django
    "Administración". Si el equipo decide otra forma de manejar
    roles, solo hay que cambiar esta funcion.
    """
    return usuario.groups.filter(name="Administración").exists()


def inicio(request):
    """Portada pública del club."""
    return render(request, "paginas/inicio.html")


@login_required
def panel(request):

    usuario = request.user

    # =====================================================
    # APODERADO
    # =====================================================
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

            apoderado.telefono = telefono
            apoderado.save()

            usuario.email = email
            usuario.save(update_fields=["email"])

            messages.success(
                request,
                "Tus datos de contacto fueron actualizados correctamente."
            )

            return redirect("panel")

        # -------------------------------------------------
        # FORMULARIO HU-01
        # -------------------------------------------------
        form = InscripcionForm()

        if (
            request.method == "POST"
            and request.POST.get("accion") == "inscripcion"
        ):

            form = InscripcionForm(request.POST)

            print("===================================")
            print("HU-01: POST RECIBIDO")
            print(request.POST)
            print("FORMULARIO VALIDO:", form.is_valid())
            print("ERRORES:", form.errors)
            print("===================================")

            if form.is_valid():

                datos = form.cleaned_data

                try:

                    with transaction.atomic():

                        # ---------------------------------
                        # 1. CREAR JUGADOR
                        # ---------------------------------
                        jugador = Jugador.objects.create(
                            rut=datos["rut"],
                            nombres=datos["nombres"],
                            apellidos=datos["apellidos"],
                            fecha_nacimiento=datos["fecha_nacimiento"],
                            rama=datos["rama"],
                            estado=Jugador.Estado.PENDIENTE,
                            procedencia=datos["procedencia"],
                            club_anterior=datos["club_anterior"],
                        )

                        # Asignar categoria segun edad y rama
                        asignar_categoria_automatica(jugador)

                        # ---------------------------------
                        # 2. RELACIONAR APODERADO - JUGADOR
                        # ---------------------------------
                        ApoderadoJugador.objects.create(
                            apoderado=apoderado,
                            jugador=jugador,
                            parentesco=datos["parentesco"],
                            es_principal=True,
                            puede_gestionar=True,
                            activo=True,
                        )

                        # ---------------------------------
                        # 3. CREAR SOLICITUD
                        # ---------------------------------
                        SolicitudInscripcion.objects.create(
                            jugador=jugador,
                            solicitante=usuario,
                            estado=SolicitudInscripcion.Estado.PENDIENTE,
                            procedencia=datos["procedencia"],
                            club_anterior=datos["club_anterior"],
                            consentimiento=datos["consentimiento"],
                        )

                    messages.success(
                        request,
                        (
                            f"La solicitud de inscripción de "
                            f"{jugador.nombres} {jugador.apellidos} "
                            "fue enviada correctamente y quedó "
                            "pendiente de revisión."
                        )
                    )

                    return redirect("panel")

                except Exception as error:

                    print("===================================")
                    print("ERROR AL GUARDAR HU-01")
                    print(error)
                    print("===================================")

                    messages.error(
                        request,
                        (
                            "No fue posible guardar la inscripción. "
                            "Revisa los datos e inténtalo nuevamente."
                        )
                    )

            else:

                messages.error(
                    request,
                    "No se pudo enviar la inscripción. Revisa los campos indicados."
                )

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
                "form": form,
            },
        )

    # =====================================================
    # ADMINISTRACIÓN DEL CLUB (HU-03)
    # =====================================================
    if es_administracion(usuario):
        return redirect("validar_fichas")

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
def validar_fichas(request):

    usuario = request.user

    if not es_administracion(usuario):
        messages.error(
            request,
            "No tienes permiso para validar fichas de inscripción."
        )
        return redirect("panel")

    # -----------------------------------------------------
    # APROBAR O RECHAZAR
    # -----------------------------------------------------
    if request.method == "POST":

        solicitud = get_object_or_404(
            SolicitudInscripcion.objects.select_related("jugador"),
            pk=request.POST.get("solicitud_id"),
        )
        accion = request.POST.get("accion")
        motivo = request.POST.get("motivo", "")
        jugador = solicitud.jugador

        try:
            with transaction.atomic():

                # Si nadie la ha revisado aun, pasa a "en revision"
                if solicitud.estado == SolicitudInscripcion.Estado.PENDIENTE:
                    marcar_solicitud_en_revision(solicitud=solicitud)

                if accion == "aprobar":
                    aprobar_solicitud_inscripcion(
                        solicitud=solicitud,
                        usuario=usuario,
                    )
                    messages.success(
                        request,
                        f"Ficha de {jugador.nombres} {jugador.apellidos} "
                        "aprobada. El jugador quedó activo."
                    )

                elif accion == "rechazar":
                    rechazar_solicitud_inscripcion(
                        solicitud=solicitud,
                        usuario=usuario,
                        motivo=motivo,
                    )
                    messages.success(
                        request,
                        f"Ficha de {jugador.nombres} {jugador.apellidos} "
                        "rechazada."
                    )

                else:
                    raise ValidationError("Acción no válida.")

        except ValidationError as error:
            messages.error(request, " ".join(error.messages))

        return redirect("validar_fichas")

    # -----------------------------------------------------
    # LISTADO DE FICHAS POR REVISAR
    # -----------------------------------------------------
    solicitudes = (
        SolicitudInscripcion.objects
        .filter(
            estado__in=[
                SolicitudInscripcion.Estado.PENDIENTE,
                SolicitudInscripcion.Estado.EN_REVISION,
            ]
        )
        .select_related("jugador", "jugador__categoria_actual")
        .prefetch_related(
            "jugador__vinculos_apoderados__apoderado",
            "jugador__alertas_salud",
        )
        .order_by("fecha_solicitud")
    )

    fichas = []

    for solicitud in solicitudes:
        jugador = solicitud.jugador

        vinculo = next(
            (v for v in jugador.vinculos_apoderados.all() if v.activo),
            None,
        )

        alertas = [
            alerta.descripcion
            for alerta in jugador.alertas_salud.all()
            if alerta.activa
        ]

        fichas.append({
            "solicitud": solicitud,
            "jugador": jugador,
            "apoderado": vinculo.apoderado if vinculo else None,
            "parentesco": vinculo.parentesco if vinculo else "",
            "alertas": alertas,
        })

    return render(
        request,
        "usuarios/validar_fichas.html",
        {
            "fichas": fichas,
        },
    )
