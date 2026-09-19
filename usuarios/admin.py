from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import UsuarioChangeForm, UsuarioCreationForm
from .models import (
    Categoria,
    Jugador,
    ReglaCategoria,
    Usuario,
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
        "categoria_actual",
        "fecha_nacimiento",
    )

    list_filter = (
        "rama",
        "estado",
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