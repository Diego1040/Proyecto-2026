from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q  # <<< NUEVO (HU-05)
from django.shortcuts import get_object_or_404, redirect, render

from .forms import InscripcionForm
from .services import (
    asignar_categoria_automatica,
    aprobar_solicitud_inscripcion,
    cambiar_categoria_manual,          
    marcar_solicitud_en_revision,
    obtener_categoria_automatica,      
    rechazar_solicitud_inscripcion,
    registrar_auditoria,               
)
from .models import (
    ApoderadoJugador,
    Categoria,                         
    HistorialCategoria,               
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

        # Al usar su propia cuenta, se desactiva la gestión activa
        # del apoderado sobre este jugador, conservando el historial.
        ApoderadoJugador.objects.filter(
            jugador=jugador_adulto,
            activo=True,
        ).update(
            activo=False,
            puede_gestionar=False,
        )

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
                         peso_kg=datos["peso_kg"],
                         talla_cm=datos["talla_cm"],
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



@login_required
def panel_jugador(request):
    """Portal personal para jugadores mayores de edad."""

    usuario = request.user
    jugador = obtener_jugador_adulto(usuario)

    # Si la cuenta no corresponde a un jugador adulto,
    # vuelve al panel normal.
    if jugador is None:
        return redirect("panel")

    # El jugador adulto administra su propia ficha.
    # Se desactiva la gestión activa del apoderado,
    # pero se conserva el historial.
    ApoderadoJugador.objects.filter(
        jugador=jugador,
        activo=True,
    ).update(
        activo=False,
        puede_gestionar=False,
    )

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



def activar_jugador(request):
    """
    Permite que un jugador mayor de edad cree y active
    su propia cuenta sin intervención del administrador.
    """

    if request.user.is_authenticated:
        jugador_actual = obtener_jugador_adulto(request.user)

        if jugador_actual is not None:
            return redirect("panel_jugador")

    datos = {
        "rut": "",
        "fecha_nacimiento": "",
    }

    if request.method == "POST":

        rut = request.POST.get("rut", "").strip()
        fecha_nacimiento = request.POST.get(
            "fecha_nacimiento",
            "",
        ).strip()

        password1 = request.POST.get(
            "password1",
            "",
        )

        password2 = request.POST.get(
            "password2",
            "",
        )

        datos["rut"] = rut
        datos["fecha_nacimiento"] = fecha_nacimiento

        # ------------------------------------------------------
        # NORMALIZAR RUT
        # ------------------------------------------------------
        rut = (
            rut
            .replace(".", "")
            .replace(" ", "")
            .upper()
        )

        # ------------------------------------------------------
        # VALIDAR CAMPOS BÁSICOS
        # ------------------------------------------------------
        if not rut or not fecha_nacimiento:
            messages.error(
                request,
                "Debes ingresar tu RUT y fecha de nacimiento.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        if not password1 or not password2:
            messages.error(
                request,
                "Debes ingresar y confirmar una contraseña.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        if password1 != password2:
            messages.error(
                request,
                "Las contraseñas no coinciden.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        # ------------------------------------------------------
        # BUSCAR JUGADOR POR RUT
        # ------------------------------------------------------
        jugador = Jugador.objects.filter(
            rut=rut
        ).select_related("usuario").first()

        if jugador is None:
            messages.error(
                request,
                "No encontramos un jugador registrado con ese RUT.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        # ------------------------------------------------------
        # COMPROBAR EDAD
        # ------------------------------------------------------
        if jugador.edad is None or jugador.edad < 18:
            messages.error(
                request,
                "La activación de cuenta solo está disponible "
                "para jugadores de 18 años o más.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        # ------------------------------------------------------
        # COMPROBAR SI YA TIENE CUENTA
        # ------------------------------------------------------
        if jugador.usuario is not None:
            messages.error(
                request,
                "Este jugador ya tiene una cuenta asociada. "
                "Puedes iniciar sesión normalmente.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        # ------------------------------------------------------
        # VALIDAR CONTRASEÑA
        # ------------------------------------------------------
        try:
            validate_password(password1)

        except ValidationError as error:
            for mensaje in error.messages:
                messages.error(
                    request,
                    mensaje,
                )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        # ------------------------------------------------------
        # CREAR CUENTA Y VINCULARLA AL JUGADOR
        # ------------------------------------------------------
        try:

            with transaction.atomic():

                User = get_user_model()

                # Comprobamos nuevamente que no exista
                # una cuenta con ese RUT.
                if User.objects.filter(
                    rut=rut
                ).exists():

                    messages.error(
                        request,
                        "Ya existe una cuenta con ese RUT.",
                    )

                    return render(
                        request,
                        "registration/activar_jugador.html",
                        datos,
                    )

                usuario = User(
                    rut=rut,
                )

                # Algunas implementaciones de usuario tienen
                # estos campos y otras no. Los rellenamos
                # solamente cuando existen.
                campos_usuario = {
                    campo.name
                    for campo in usuario._meta.fields
                }

                if "username" in campos_usuario:
                    usuario.username = rut

                if "first_name" in campos_usuario:
                    usuario.first_name = jugador.nombres

                if "last_name" in campos_usuario:
                    usuario.last_name = jugador.apellidos

                if "nombres" in campos_usuario:
                    usuario.nombres = jugador.nombres

                if "apellidos" in campos_usuario:
                    usuario.apellidos = jugador.apellidos

                usuario.set_password(password1)

                usuario.save()

                # Vincular cuenta con jugador.
                jugador.usuario = usuario

                jugador.save(
                    update_fields=[
                        "usuario",
                        "updated_at",
                    ]
                )

                # El jugador adulto pasa a administrar
                # su propia información.
                ApoderadoJugador.objects.filter(
                    jugador=jugador,
                    activo=True,
                ).update(
                    activo=False,
                    puede_gestionar=False,
                )

        except IntegrityError:
            messages.error(
                request,
                "No fue posible crear la cuenta porque "
                "el RUT ya está registrado.",
            )

            return render(
                request,
                "registration/activar_jugador.html",
                datos,
            )

        # ------------------------------------------------------
        # INICIAR SESIÓN AUTOMÁTICAMENTE
        # ------------------------------------------------------
        login(request, usuario)

        messages.success(
            request,
            "Tu cuenta de jugador fue activada correctamente.",
        )

        return redirect("panel_jugador")

    return render(
        request,
        "registration/activar_jugador.html",
        datos,
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