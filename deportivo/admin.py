from django.contrib import admin

# Register your models here.
from .models import Entrenamiento, Asistencia, PerfilEntrenador

@admin.register(PerfilEntrenador)
class PerfilEntrenadorAdmin(admin.ModelAdmin):
    list_display = ('usuario',)
    filter_horizontal = ('categorias',)

@admin.register(Entrenamiento)
class EntrenamientoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'fecha', 'duracion', 'creado_por')
    list_filter = ('categoria', 'fecha')

@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ('entrenamiento', 'jugador', 'estado', 'registrado_por', 'registrado_en')
    list_filter = ('estado', 'entrenamiento__categoria')