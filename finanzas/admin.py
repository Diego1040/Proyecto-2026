from django.contrib import admin

from .models import Cuota, Pago


@admin.register(Cuota)
class CuotaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jugador",
        "periodo",
        "monto",
        "fecha_vencimiento",
        "estado",
    )

    list_filter = (
        "estado",
        "periodo",
    )

    search_fields = (
        "jugador__rut",
        "jugador__nombres",
        "jugador__apellidos",
        "concepto",
    )

    list_select_related = ("jugador",)

    readonly_fields = (
        "creado_en",
        "actualizado_en",
    )


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = (
        "orden_compra",
        "cuota",
        "usuario",
        "monto",
        "estado",
        "creado_en",
        "fecha_transaccion",
    )

    list_filter = (
        "estado",
        "creado_en",
    )

    search_fields = (
        "orden_compra",
        "cuota__jugador__rut",
        "cuota__jugador__nombres",
        "cuota__jugador__apellidos",
        "usuario__rut",
    )

    list_select_related = (
        "cuota",
        "cuota__jugador",
        "usuario",
    )

    # Los intentos de pago se consultan, pero no se crean
    # ni modifican manualmente desde Django Admin.
    readonly_fields = (
        "cuota",
        "usuario",
        "orden_compra",
        "session_id",
        "token_ws",
        "monto",
        "estado",
        "codigo_autorizacion",
        "codigo_respuesta",
        "fecha_transaccion",
        "creado_en",
        "actualizado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    exclude = ("token_ws",)