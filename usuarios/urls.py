from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
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
