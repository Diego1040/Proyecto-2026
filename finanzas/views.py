import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from usuarios.models import ApoderadoJugador

from .models import Cuota, Pago
from .webpay_service import (
    obtener_transaccion_webpay,
    URL_WEBPAY_INTEGRACION,
)

from datetime import timedelta
from .webpay_service import obtener_transaccion_webpay


from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Sum

from .forms import CuotaForm, PagoManualForm
from .permissions import tesoreria_required



logger = logging.getLogger(__name__)


def usuario_puede_pagar_cuota(usuario, cuota):
    """Comprueba que el usuario sea el jugador o su apoderado autorizado."""

    if cuota.jugador.usuario_id == usuario.pk:
        return True

    return ApoderadoJugador.objects.filter(
        jugador_id=cuota.jugador_id,
        apoderado__usuario_id=usuario.pk,
        activo=True,
        puede_gestionar=True,
    ).exists()


@login_required
def mis_cuotas(request):
    """Muestra exclusivamente las cuotas de jugadores autorizados."""

    pago_en_curso = Pago.objects.filter(
        cuota_id=OuterRef("pk"),
        estado=Pago.Estado.INICIADO,
    )

    cuotas = (
        Cuota.objects.select_related("jugador")
        .filter(
            Q(jugador__usuario_id=request.user.pk)
            | Q(
                jugador__vinculos_apoderados__apoderado__usuario_id=request.user.pk,
                jugador__vinculos_apoderados__activo=True,
                jugador__vinculos_apoderados__puede_gestionar=True,
            )
        )
        .annotate(pago_en_curso=Exists(pago_en_curso))
        .distinct()
    )

    return render(
        request,
        "finanzas/mis_cuotas.html",
        {"cuotas": cuotas},
    )


@login_required
@require_POST
def iniciar_pago(request, cuota_id):
    """Crea un intento de pago y solicita una transacción a Webpay Plus."""

    cuota = get_object_or_404(
        Cuota.objects.select_related("jugador"),
        pk=cuota_id,
    )

    if not usuario_puede_pagar_cuota(request.user, cuota):
        messages.error(request, "No tienes autorización para pagar esta cuota.")
        return redirect("finanzas:mis_cuotas")

    if cuota.estado != Cuota.Estado.PENDIENTE:
        messages.warning(request, "Esta cuota no está pendiente de pago.")
        return redirect("finanzas:mis_cuotas")

    if Pago.objects.filter(
        cuota=cuota,
        estado=Pago.Estado.CONFIRMADO,
    ).exists():
        messages.warning(request, "Esta cuota ya tiene un pago confirmado.")
        return redirect("finanzas:mis_cuotas")

    if Pago.objects.filter(
        cuota=cuota,
        estado=Pago.Estado.INICIADO,
    ).exists():
        messages.warning(
            request,
            "Ya existe un intento de pago en curso para esta cuota. "
            "No vuelvas a pagar hasta verificar su estado.",
        )
        return redirect("finanzas:mis_cuotas")

    # El monto se toma de la base de datos, nunca del formulario.
    pago = Pago.objects.create(
        cuota=cuota,
        usuario=request.user,
        monto=cuota.monto,
    )

    url_retorno = request.build_absolute_uri(
        reverse("finanzas:retorno_webpay")
    )

    try:
        tx = obtener_transaccion_webpay()

        respuesta = tx.create(
            pago.orden_compra,
            pago.session_id,
            int(pago.monto),
            url_retorno,
        )

        token_ws = respuesta.get("token")
        webpay_url = respuesta.get("url")

        if (
            not isinstance(token_ws, str)
            or not token_ws
            or not isinstance(webpay_url, str)
            or not webpay_url.startswith("https://webpay3gint.transbank.cl/")
        ):
            raise ValueError("La respuesta de creación de Webpay no es válida.")

        pago.token_ws = token_ws
        pago.save(update_fields=["token_ws", "actualizado_en"])

    except Exception:
        logger.exception(
            "No se pudo iniciar el pago %s",
            pago.orden_compra,
        )

        pago.estado = Pago.Estado.ERROR
        pago.save(update_fields=["estado", "actualizado_en"])

        messages.error(
            request,
            "No se pudo iniciar el pago. Puedes consultar su estado "
            "antes de intentar nuevamente.",
        )
        return redirect("finanzas:mis_cuotas")

    return render(
        request,
        "finanzas/redirigir_webpay.html",
        {
            "webpay_url": webpay_url,
            "token_ws": token_ws,
        },
    )

@login_required
@require_POST
def reanudar_pago(request, cuota_id):
    cuota = get_object_or_404(
        Cuota.objects.select_related("jugador"),
        pk=cuota_id,
    )

    if not usuario_puede_pagar_cuota(request.user, cuota):
        messages.error(
            request,
            "No tienes autorización para gestionar esta cuota.",
        )
        return redirect("finanzas:mis_cuotas")

    if cuota.estado != Cuota.Estado.PENDIENTE:
        messages.warning(
            request,
            "La cuota ya no está pendiente.",
        )
        return redirect("finanzas:mis_cuotas")

    if Pago.objects.filter(
        cuota=cuota,
        estado=Pago.Estado.CONFIRMADO,
    ).exists():
        messages.warning(
            request,
            "La cuota ya tiene un pago confirmado.",
        )
        return redirect("finanzas:mis_cuotas")

    pago = (
        Pago.objects.filter(
            cuota=cuota,
            estado=Pago.Estado.INICIADO,
        )
        .exclude(token_ws="")
        .order_by("-creado_en")
        .first()
    )

    if pago is None:
        messages.warning(
            request,
            "No existe un intento de pago que se pueda recuperar.",
        )
        return redirect("finanzas:mis_cuotas")

    # Consultar el estado real de la transacción en Transbank.
    try:
        respuesta_estado = obtener_transaccion_webpay().status(
            pago.token_ws
        )

        monto_transbank = Decimal(
            str(respuesta_estado.get("amount"))
        )

        datos_coinciden = (
            monto_transbank == pago.monto
            and respuesta_estado.get("buy_order") == pago.orden_compra
            and respuesta_estado.get("session_id") == pago.session_id
        )

    except Exception:
        logger.exception(
            "No se pudo consultar el intento %s",
            pago.orden_compra,
        )
        messages.error(
            request,
            "No se pudo verificar el estado en Transbank. "
            "No se iniciará otro pago.",
        )
        return redirect("finanzas:mis_cuotas")

    if not datos_coinciden:
        messages.error(
            request,
            "Los datos de la transacción no coinciden. "
            "Se requiere revisión antes de continuar.",
        )
        return redirect("finanzas:mis_cuotas")

    estado_transbank = respuesta_estado.get("status")

    # No crear otro intento si Transbank informa un estado diferente.
    if estado_transbank != "INITIALIZED":
        messages.warning(
            request,
            "Transbank informa un estado distinto de INITIALIZED. "
            "No se creará otra transacción automáticamente.",
        )
        return redirect("finanzas:mis_cuotas")

    antiguedad = timezone.now() - pago.creado_en

    # Si el intento es reciente, no reutilizar automáticamente su token.
    if antiguedad < timedelta(minutes=5):
        messages.warning(
            request,
            "El intento de pago todavía está dentro de su ventana "
            "de vigencia. Espera al menos cinco minutos desde su inicio "
            "y vuelve a verificar su estado.",
        )
        return redirect("finanzas:mis_cuotas")

    # El intento antiguo sigue INITIALIZED.
    # Conservamos el registro y lo marcamos como expirado.
    pago.estado = Pago.Estado.EXPIRADO
    pago.save(
        update_fields=["estado", "actualizado_en"]
    )

    # Crear un nuevo intento con orden y sesión nuevos.
    nuevo_pago = Pago.objects.create(
        cuota=cuota,
        usuario=request.user,
        monto=cuota.monto,
    )

    try:
        url_retorno = request.build_absolute_uri(
            reverse("finanzas:retorno_webpay")
        )

        respuesta_nueva = obtener_transaccion_webpay().create(
            nuevo_pago.orden_compra,
            nuevo_pago.session_id,
            int(nuevo_pago.monto),
            url_retorno,
        )

        nuevo_token = respuesta_nueva.get("token")
        nueva_url = respuesta_nueva.get("url")

        if (
            not isinstance(nuevo_token, str)
            or not nuevo_token
            or not isinstance(nueva_url, str)
            or not nueva_url.startswith(
                "https://webpay3gint.transbank.cl/"
            )
        ):
            raise ValueError(
                "Transbank no devolvió una URL o un token válido."
            )

        nuevo_pago.token_ws = nuevo_token
        nuevo_pago.save(
            update_fields=["token_ws", "actualizado_en"]
        )

    except Exception:
        logger.exception(
            "No se pudo crear un nuevo intento para la cuota %s",
            cuota.pk,
        )

        nuevo_pago.estado = Pago.Estado.ERROR
        nuevo_pago.save(
            update_fields=["estado", "actualizado_en"]
        )

        messages.error(
            request,
            "No se pudo generar un nuevo intento de pago. "
            "La cuota sigue pendiente.",
        )
        return redirect("finanzas:mis_cuotas")

    return render(
        request,
        "finanzas/redirigir_webpay.html",
        {
            "webpay_url": nueva_url,
            "token_ws": nuevo_token,
        },
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def retorno_webpay(request):
    """
    Recibe el retorno de Webpay.

    Una cuota solo se marca pagada después de confirmar la transacción
    y verificar estado, importe, orden de compra y sesión.
    """

    token_ws = (
        request.POST.get("token_ws")
        or request.GET.get("token_ws")
    )

    # El comprador pudo cancelar la operación.
    token_cancelacion = (
        request.POST.get("TBK_TOKEN")
        or request.GET.get("TBK_TOKEN")
    )

    if not token_ws and token_cancelacion:
        pago = Pago.objects.filter(token_ws=token_cancelacion).first()

        if pago and pago.estado == Pago.Estado.INICIADO:
            pago.estado = Pago.Estado.ANULADO
            pago.save(update_fields=["estado", "actualizado_en"])

        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "cancelado",
                "mensaje": "El pago fue cancelado. La cuota sigue pendiente.",
                "pago": pago,
            },
        )

    if not token_ws:
        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "error",
                "mensaje": (
                    "No se recibió un identificador válido de la transacción."
                ),
                "pago": None,
            },
            status=400,
        )

    pago = Pago.objects.select_related("cuota", "cuota__jugador").filter(
        token_ws=token_ws,
    ).first()

    if pago is None:
        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "error",
                "mensaje": "No encontramos el intento de pago correspondiente.",
                "pago": None,
            },
            status=400,
        )

    # Hacer el retorno idempotente: no confirmar dos veces un pago registrado.
    if pago.estado == Pago.Estado.CONFIRMADO:
        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "confirmado",
                "mensaje": "Este pago ya fue confirmado.",
                "pago": pago,
            },
        )

    if pago.estado != Pago.Estado.INICIADO:
        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "error",
                "mensaje": (
                    "Este intento ya no está en estado de pago iniciado. "
                    "Consulta su estado antes de volver a pagar."
                ),
                "pago": pago,
            },
        )

    try:
        respuesta = obtener_transaccion_webpay().commit(token_ws)
    except Exception:
        logger.exception(
            "No se pudo confirmar el pago %s",
            pago.orden_compra,
        )

        # Se deja INICIADO para impedir otro intento potencialmente duplicado.
        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "pendiente",
                "mensaje": (
                    "No pudimos verificar la respuesta de Webpay. "
                    "Por seguridad, no vuelvas a pagar todavía. "
                    "Consulta el estado de la operación."
                ),
                "pago": pago,
            },
        )

    try:
        codigo_respuesta = int(respuesta.get("response_code"))
    except (TypeError, ValueError):
        codigo_respuesta = None

    try:
        monto_respuesta = Decimal(str(respuesta.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        monto_respuesta = None

    estado_respuesta = respuesta.get("status")
    autorizado = (
        estado_respuesta == "AUTHORIZED"
        and codigo_respuesta == 0
    )

    datos_coinciden = (
        monto_respuesta == pago.monto
        and respuesta.get("buy_order") == pago.orden_compra
        and respuesta.get("session_id") == pago.session_id
    )

    fecha = parse_datetime(respuesta.get("transaction_date", "") or "")

    if fecha is not None and timezone.is_naive(fecha):
        fecha = timezone.make_aware(
            fecha,
            timezone.get_current_timezone(),
        )

    fecha = fecha or timezone.now()

    if not autorizado:
        pago.estado = Pago.Estado.RECHAZADO
        pago.codigo_respuesta = codigo_respuesta
        pago.fecha_transaccion = fecha
        pago.save(
            update_fields=[
                "estado",
                "codigo_respuesta",
                "fecha_transaccion",
                "actualizado_en",
            ]
        )

        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "rechazado",
                "mensaje": (
                    "Webpay no autorizó el pago. La cuota continúa pendiente."
                ),
                "pago": pago,
            },
        )

    if not datos_coinciden:
        logger.error(
            "Datos de retorno no coinciden para el pago %s",
            pago.orden_compra,
        )

        pago.estado = Pago.Estado.ERROR
        pago.codigo_respuesta = codigo_respuesta
        pago.fecha_transaccion = fecha
        pago.save(
            update_fields=[
                "estado",
                "codigo_respuesta",
                "fecha_transaccion",
                "actualizado_en",
            ]
        )

        return render(
            request,
            "finanzas/resultado_pago.html",
            {
                "resultado": "error",
                "mensaje": (
                    "La respuesta no coincide con los datos del pago. "
                    "La operación requiere revisión antes de actualizar la cuota."
                ),
                "pago": pago,
            },
        )

    with transaction.atomic():
        pago_actual = Pago.objects.select_for_update().get(pk=pago.pk)
        cuota_actual = Cuota.objects.select_for_update().get(
            pk=pago_actual.cuota_id,
        )

        if pago_actual.estado == Pago.Estado.CONFIRMADO:
            resultado = "confirmado"
            mensaje = "Este pago ya fue confirmado."

        elif (
            cuota_actual.estado != Cuota.Estado.PENDIENTE
            or Pago.objects.filter(
                cuota=cuota_actual,
                estado=Pago.Estado.CONFIRMADO,
            ).exclude(pk=pago_actual.pk).exists()
        ):
            # Webpay respondió autorización, pero existe una inconsistencia local.
            # No marcamos la cuota pagada automáticamente.
            pago_actual.estado = Pago.Estado.ERROR
            pago_actual.codigo_respuesta = codigo_respuesta
            pago_actual.codigo_autorizacion = (
                respuesta.get("authorization_code", "") or ""
            )
            pago_actual.fecha_transaccion = fecha
            pago_actual.save()

            resultado = "error"
            mensaje = (
                "Webpay autorizó la operación, pero la cuota tiene un "
                "estado incompatible. Se requiere una revisión administrativa."
            )

        else:
            pago_actual.estado = Pago.Estado.CONFIRMADO
            pago_actual.codigo_respuesta = codigo_respuesta
            pago_actual.codigo_autorizacion = (
                respuesta.get("authorization_code", "") or ""
            )
            pago_actual.fecha_transaccion = fecha
            pago_actual.save()

            cuota_actual.estado = Cuota.Estado.PAGADA
            cuota_actual.save(
                update_fields=["estado", "actualizado_en"]
            )

            resultado = "confirmado"
            mensaje = "El pago fue confirmado correctamente."

    pago.refresh_from_db()

    return render(
        request,
        "finanzas/resultado_pago.html",
        {
            "resultado": resultado,
            "mensaje": mensaje,
            "pago": pago,
        },
    )


def contexto_tesoreria(request):
    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)

    pagos_mes = Pago.objects.filter(
        estado=Pago.Estado.CONFIRMADO,
        fecha_transaccion__date__gte=inicio_mes,
        fecha_transaccion__date__lte=hoy,
    )

    recaudado_mes = (
        pagos_mes.aggregate(total=Sum("monto"))["total"]
        or Decimal("0")
    )

    cuotas_pendientes = Cuota.objects.filter(
        estado=Cuota.Estado.PENDIENTE
    ).count()

    pagos_webpay_mes = pagos_mes.filter(
        medio_pago="WEBPAY"
    ).count()

    pagos_manuales_mes = pagos_mes.exclude(
        medio_pago="WEBPAY"
    ).count()

    intentos_en_curso = Pago.objects.filter(
        cuota_id=OuterRef("pk"),
        estado=Pago.Estado.INICIADO,
    )

    lista_cuotas = (
        Cuota.objects.select_related("jugador")
        .prefetch_related("pagos")
        .annotate(
            tiene_pago_iniciado=Exists(intentos_en_curso)
        )
        .order_by(
            "-periodo",
            "jugador__apellidos",
            "jugador__nombres",
        )
    )

    pagina = Paginator(lista_cuotas, 25).get_page(
        request.GET.get("page")
    )

    ultimos_pagos = (
        Pago.objects.select_related(
            "cuota__jugador",
            "usuario",
        )
        .order_by("-creado_en")[:10]
    )

    return {
        "hoy": hoy,
        "recaudado_mes": recaudado_mes,
        "cuotas_pendientes": cuotas_pendientes,
        "pagos_webpay_mes": pagos_webpay_mes,
        "pagos_manuales_mes": pagos_manuales_mes,
        "pagina": pagina,
        "ultimos_pagos": ultimos_pagos,
    }


@login_required
@tesoreria_required
def panel_tesoreria(request):
    contexto = contexto_tesoreria(request)

    return render(
        request,
        "finanzas/tesoreria.html",
        contexto,
    )


@login_required
@tesoreria_required
def crear_cuota(request):
    if request.method == "POST":
        form = CuotaForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    cuota = form.save()
            except IntegrityError:
                form.add_error(
                    None,
                    "Ya existe una cuota para ese jugador y período.",
                )
            else:
                messages.success(
                    request,
                    f"Se creó la cuota de {cuota.jugador.nombres} "
                    f"{cuota.jugador.apellidos}.",
                )
                return redirect("finanzas:tesoreria")
    else:
        form = CuotaForm()

    return render(
        request,
        "finanzas/crear_cuota.html",
        {"form": form},
    )


@login_required
@tesoreria_required
@require_POST
def registrar_pago_manual(request, cuota_id):
    form = PagoManualForm(request.POST)

    if not form.is_valid():
        errores = "; ".join(
            error
            for errores_campo in form.errors.values()
            for error in errores_campo
        )
        messages.error(
            request,
            f"Revisa los datos del pago: {errores}",
        )
        return redirect("finanzas:tesoreria")

    try:
        with transaction.atomic():
            cuota = get_object_or_404(
                Cuota.objects.select_for_update(),
                pk=cuota_id,
            )

            if cuota.estado != Cuota.Estado.PENDIENTE:
                messages.warning(
                    request,
                    "La cuota ya no está pendiente.",
                )
                return redirect("finanzas:tesoreria")

            if Pago.objects.filter(
                cuota=cuota,
                estado=Pago.Estado.CONFIRMADO,
            ).exists():
                messages.warning(
                    request,
                    "La cuota ya tiene un pago confirmado.",
                )
                return redirect("finanzas:tesoreria")

            if Pago.objects.filter(
                cuota=cuota,
                estado=Pago.Estado.INICIADO,
            ).exists():
                messages.error(
                    request,
                    "Existe un intento de Webpay sin resolver. "
                    "Verifica su estado antes de registrar un pago manual.",
                )
                return redirect("finanzas:tesoreria")

            pago = Pago.objects.create(
                cuota=cuota,
                usuario=request.user,
                monto=cuota.monto,
                estado=Pago.Estado.CONFIRMADO,
                medio_pago=form.cleaned_data["medio_pago"],
                referencia=form.cleaned_data["referencia"].strip(),
                fecha_transaccion=timezone.now(),
            )

            cuota.estado = Cuota.Estado.PAGADA
            cuota.save(
                update_fields=["estado", "actualizado_en"]
            )

    except IntegrityError:
        messages.error(
            request,
            "No se pudo registrar el pago porque existe "
            "una operación incompatible. Revisa el estado de la cuota.",
        )
        return redirect("finanzas:tesoreria")

    messages.success(
        request,
        f"Pago manual de ${pago.monto:,.0f} registrado correctamente.",
    )
    return redirect("finanzas:tesoreria")
