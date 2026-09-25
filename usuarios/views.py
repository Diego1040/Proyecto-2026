from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .forms import InscripcionForm
from .models import (
    ApoderadoJugador,
    Jugador,
    SolicitudInscripcion,
)


def inicio(request):
    """Portada publica del club."""
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
        
        if request.method == "POST":
            print("===================================")
            print("POST RECIBIDO")
            print(request.POST)
            print("===================================")





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
        # INSCRIPCIÓN HU-01
        # -------------------------------------------------
        form = InscripcionForm()

        if (
            request.method == "POST"
            and request.POST.get("accion") == "inscripcion"
        ):

            form = InscripcionForm(request.POST)

            if form.is_valid():

                datos = form.cleaned_data

                with transaction.atomic():

                    # 1. Crear jugador
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

                    # 2. Relacionar apoderado y jugador
                    ApoderadoJugador.objects.create(
                        apoderado=apoderado,
                        jugador=jugador,
                        parentesco=datos["parentesco"],
                        es_principal=True,
                        puede_gestionar=True,
                        activo=True,
                    )

                    # 3. Crear solicitud
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
                        "fue enviada correctamente y quedó pendiente "
                        "de revisión."
                    )
                )

                # Evita volver a enviar el formulario al actualizar
                return redirect("panel")

        # -------------------------------------------------
        # OBTENER EL PUPILO DEL APODERADO
        # -------------------------------------------------
        jugador = (
            apoderado.vinculos_jugadores
            .filter(activo=True)
            .select_related("jugador__categoria_actual")
            .order_by("-es_principal", "-created_at")
            .first()
        )

        # -------------------------------------------------
        # RENDER
        # -------------------------------------------------
        return render(
            request,
            "usuarios/panel_apoderado.html",
            {
                "perfil": "Apoderado",
                "apoderado": apoderado,
                "jugador": jugador.jugador if jugador else None,
                "form": form,
            },
        )

    # =====================================================
    # ADMINISTRACIÓN
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