from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import UsuarioChangeForm, UsuarioCreationForm
from .models import (
    Categoria,
    Jugador,
    ReglaCategoria,
    Usuario,
    Apoderado,
    ApoderadoJugador,
    SolicitudInscripcion,
    HistorialCategoria,
    AlertaSalud,
    Auditoria,
    PeriodoInactividad,
)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    add_form = UsuarioCreationForm
    form = UsuarioChangeForm
    model = Usuario

    list_display = (
        "rut",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
    )

    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
    )

    search_fields = (
        "rut",
        "email",
    )

    ordering = (
        "rut",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "rut",
                    "password",
                )
            },
        ),
        (
            "Información opcional",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                )
            },
        ),
        (
            "Permisos",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Fechas importantes",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                    "updated_at",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "rut",
                    "email",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )

    readonly_fields = (
        "last_login",
        "date_joined",
        "updated_at",
    )

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "rama",
        "activa",
        "orden",
    )

    list_filter = (
        "rama",
        "activa",
    )

    search_fields = (
        "nombre",
    )

    ordering = (
        "orden",
        "nombre",
    )


@admin.register(ReglaCategoria)
class ReglaCategoriaAdmin(admin.ModelAdmin):
    list_display = (
        "categoria",
        "edad_min",
        "edad_max",
        "temporada",
        "activa",
    )

    list_filter = (
        "temporada",
        "activa",
        "categoria__rama",
    )

    search_fields = (
        "categoria__nombre",
    )

    ordering = (
        "-temporada",
        "edad_min",
    )


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = (
        "rut",
        "nombres",
        "apellidos",
        "rama",
        "estado",
        "becado",
        "categoria_actual",
        "fecha_nacimiento",
    )

    list_filter = (
        "rama",
        "estado",
        "becado",
        "categoria_actual",
        "procedencia",
    )

    search_fields = (
        "rut",
        "nombres",
        "apellidos",
    )

    ordering = (
        "apellidos",
        "nombres",
    )

    autocomplete_fields = (
        "usuario",
        "categoria_actual",
    )

    list_editable = (
        "becado",
    )

    def get_readonly_fields(self, request, obj=None):
        if (
            obj
            and obj.estado != Jugador.Estado.PENDIENTE
        ):
            return ("estado",)

        return ()


@admin.register(Apoderado)
class ApoderadoAdmin(admin.ModelAdmin):
    list_display = (
        "rut",
        "nombres",
        "apellidos",
        "telefono",
        "usuario",
    )

    search_fields = (
        "rut",
        "nombres",
        "apellidos",
        "telefono",
    )

    ordering = (
        "apellidos",
        "nombres",
    )

    autocomplete_fields = (
        "usuario",
    )


@admin.register(ApoderadoJugador)
class ApoderadoJugadorAdmin(admin.ModelAdmin):
    list_display = (
        "apoderado",
        "jugador",
        "parentesco",
        "es_principal",
        "puede_gestionar",
        "activo",
    )

    list_filter = (
        "es_principal",
        "puede_gestionar",
        "activo",
    )

    search_fields = (
        "apoderado__rut",
        "apoderado__nombres",
        "apoderado__apellidos",
        "jugador__rut",
        "jugador__nombres",
        "jugador__apellidos",
    )

    autocomplete_fields = (
        "apoderado",
        "jugador",
    )

@admin.register(SolicitudInscripcion)
class SolicitudInscripcionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "jugador",
        "estado",
        "fecha_solicitud",
        "revisado_por",
        "fecha_revision",
    )

    list_filter = (
        "estado",
        "procedencia",
        "fecha_solicitud",
    )

    search_fields = (
        "jugador__rut",
        "jugador__nombres",
        "jugador__apellidos",
    )

    autocomplete_fields = (
        "jugador",
        "solicitante",
        "revisado_por",
    )

    readonly_fields = (
        "fecha_solicitud",
        "estado",
        "revisado_por",
        "fecha_revision",
        "motivo_rechazo",
        "usuario_autorizado",
        "jugador",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Las solicitudes y sus resoluciones se conservan para trazabilidad.
        return False

@admin.register(HistorialCategoria)
class HistorialCategoriaAdmin(admin.ModelAdmin):
    list_display = (
        "jugador",
        "categoria_anterior",
        "categoria_nueva",
        "tipo_cambio",
        "cambiado_por",
        "fecha",
    )

    list_filter = (
        "tipo_cambio",
        "categoria_nueva",
        "fecha",
    )

    search_fields = (
        "jugador__rut",
        "jugador__nombres",
        "jugador__apellidos",
    )

    autocomplete_fields = (
        "jugador",
        "categoria_anterior",
        "categoria_nueva",
        "cambiado_por",
    )

    readonly_fields = (
        "fecha",
    )


@admin.register(AlertaSalud)
class AlertaSaludAdmin(admin.ModelAdmin):
    list_display = (
        "jugador",
        "tipo",
        "activa",
        "updated_at",
    )

    list_filter = (
        "activa",
        "tipo",
    )

    search_fields = (
        "jugador__rut",
        "jugador__nombres",
        "jugador__apellidos",
        "tipo",
    )

    autocomplete_fields = (
        "jugador",
    )

@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = (
        "accion",
        "entidad",
        "entidad_id",
        "usuario",
        "fecha",
    )

    list_filter = (
        "accion",
        "entidad",
        "fecha",
    )

    search_fields = (
        "accion",
        "entidad",
        "usuario__rut",
    )

    readonly_fields = (
        "usuario",
        "accion",
        "entidad",
        "entidad_id",
        "detalle",
        "fecha",
    )

    ordering = (
        "-fecha",
    )


@admin.register(PeriodoInactividad)
class PeriodoInactividadAdmin(admin.ModelAdmin):
    list_display = (
        "jugador",
        "motivo",
        "fecha_inicio",
        "fecha_reactivacion",
        "registrado_por",
        "reactivado_por",
    )

    list_filter = (
        "motivo",
        "fecha_inicio",
        "fecha_reactivacion",
    )

    search_fields = (
        "jugador__rut",
        "jugador__nombres",
        "jugador__apellidos",
        "observaciones",
    )

    autocomplete_fields = (
        "jugador",
        "registrado_por",
        "reactivado_por",
    )

    def get_fields(self, request, obj=None):
        if obj is None:
            return (
                "jugador",
                "motivo",
                "fecha_inicio",
                "observaciones",
            )

        return (
            "jugador",
            "motivo",
            "fecha_inicio",
            "fecha_reactivacion",
            "observaciones",
            "registrado_por",
            "reactivado_por",
            "creado_en",
            "actualizado_en",
        )

    def get_readonly_fields(self, request, obj=None):
        campos_auditoria = (
            "registrado_por",
            "reactivado_por",
            "creado_en",
            "actualizado_en",
        )

        if obj is None:
            return ()

        if obj.fecha_reactivacion is not None:
            return (
                "jugador",
                "motivo",
                "fecha_inicio",
                "fecha_reactivacion",
                "observaciones",
                *campos_auditoria,
            )

        return (
            "jugador",
            "motivo",
            "fecha_inicio",
            *campos_auditoria,
        )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.registrado_por = request.user
        else:
            anterior = PeriodoInactividad.objects.get(
                pk=obj.pk
            )

            if (
                anterior.fecha_reactivacion is None
                and obj.fecha_reactivacion is not None
            ):
                obj.reactivado_por = request.user

        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False