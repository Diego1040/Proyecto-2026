from django.urls import path

from . import views


app_name = "finanzas"

urlpatterns = [
    path(
        "mis-cuotas/",
        views.mis_cuotas,
        name="mis_cuotas",
    ),

        path(
        "pagos/<int:pago_id>/comprobante/",
        views.comprobante_pago,
        name="comprobante_pago",
    ),

    path(
        "cuotas/<int:cuota_id>/pagar/",
        views.iniciar_pago,
        name="iniciar_pago",
    ),
    path(
        "webpay/retorno/",
        views.retorno_webpay,
        name="retorno_webpay",
    ),
    path(
    "cuotas/<int:cuota_id>/reanudar/",
    views.reanudar_pago,
    name="reanudar_pago",
),

path(
    "tesoreria/",
    views.panel_tesoreria,
    name="tesoreria",
),
path(
    "tesoreria/cuotas/nueva/",
    views.crear_cuota,
    name="crear_cuota",
),
path(
    "tesoreria/cuotas/<int:cuota_id>/registrar-pago/",
    views.registrar_pago_manual,
    name="registrar_pago_manual",
),

    path(
        "pagos/<int:pago_id>/comprobante/pdf/",
        views.descargar_comprobante_pdf,
        name="descargar_comprobante_pdf",
    ),
]