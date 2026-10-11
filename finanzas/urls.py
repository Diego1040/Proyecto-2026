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
]