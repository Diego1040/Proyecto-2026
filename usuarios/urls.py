from django.urls import path
from django.views.generic import TemplateView

from . import views, views_importacion_jugadores
from . import views_gestion_usuarios
from . import views_mi_cuenta

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("panel/", views.panel, name="panel"),
    path("cuenta/datos/", views_mi_cuenta.editar_mi_cuenta, name="editar_mi_cuenta"),
    path("administracion/usuarios/", views_gestion_usuarios.listado_usuarios, name="gestion_usuarios"),
    path("administracion/usuarios/<int:pk>/", views_gestion_usuarios.detalle_usuario, name="detalle_usuario"),
    path("administracion/importar-jugadores/", views_importacion_jugadores.importacion_jugadores,
         name="importacion_jugadores"),
    path("administracion/importar-jugadores/<uuid:proceso_id>/confirmar/",
         views_importacion_jugadores.importacion_jugadores_confirmar, name="importacion_jugadores_confirmar"),
    path("administracion/importar-jugadores/<uuid:proceso_id>/reporte/",
         views_importacion_jugadores.importacion_jugadores_reporte, name="importacion_jugadores_reporte"),
    path("administracion/importar-jugadores/<uuid:proceso_id>/resultado/",
         views_importacion_jugadores.importacion_jugadores_resultado, name="importacion_jugadores_resultado"),
    path("perfil/jugador/", views.perfil_jugador, name="perfil_jugador"),
    path("perfil/apoderado/", views.perfil_apoderado, name="perfil_apoderado"),
    path("activar-cuenta/", views.activar_cuenta, name="activar_cuenta"),
    path("activar-cuenta/enviada/", TemplateView.as_view(
        template_name="registration/activacion_enviada.html"), name="activacion_enviada"),
    path("activar-cuenta/completa/", TemplateView.as_view(
        template_name="registration/activacion_completa.html"), name="activacion_completa"),
    path("activar-cuenta/<uidb64>/<token>/", views.ConfirmarActivacionView.as_view(),
         name="confirmar_activacion"),
    path(
        "administracion/fichas/",
        views.validar_fichas,
        name="validar_fichas",
    ),
    path(
        "administracion/categorias/",
        views.categorias_jugadores,
        name="categorias_jugadores",
    ),
 path("jugador/", views.panel_jugador, name="panel_jugador"),
    path(
        "perfil/apoderado/agregar-jugador/",
        views.agregar_jugador_apoderado,
        name="agregar_jugador_apoderado",
    ),
    path("inscripcion/", views.inscripcion_publica, name="inscripcion"),
    path("inscripcion/gracias/", views.inscripcion_exito, name="inscripcion_exito"),
    path("gestion/solicitudes/", views.solicitudes_administracion, name="solicitudes_administracion"),
    path("gestion/solicitudes/<int:pk>/", views.solicitud_detalle, name="solicitud_detalle"),
    path("gestion/solicitudes/<int:pk>/revision/", views.solicitud_iniciar_revision, name="solicitud_iniciar_revision"),
    path("gestion/solicitudes/<int:pk>/aprobar/", views.solicitud_aprobar, name="solicitud_aprobar"),
    path("gestion/solicitudes/<int:pk>/rechazar/", views.solicitud_rechazar, name="solicitud_rechazar"),
]
