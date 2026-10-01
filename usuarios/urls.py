from django.urls import path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("activar-cuenta/", views.activar_cuenta, name="activar_cuenta"),
    path(
        "activar-cuenta/enviada/",
        TemplateView.as_view(template_name="registration/activacion_enviada.html"),
        name="activacion_enviada",
    ),
    path(
        "activar-cuenta/<uidb64>/<token>/",
        views.ConfirmarActivacionView.as_view(),
        name="confirmar_activacion",
    ),
    path(
        "activar-cuenta/completa/",
        TemplateView.as_view(template_name="registration/activacion_completa.html"),
        name="activacion_completa",
    ),
    path("panel/", views.panel, name="panel"),
    path("perfil/jugador/", views.perfil_jugador, name="perfil_jugador"),
    path("perfil/apoderado/", views.perfil_apoderado, name="perfil_apoderado"),
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
