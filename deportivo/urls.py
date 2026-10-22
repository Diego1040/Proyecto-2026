from django.urls import path
 
from . import views
 
app_name = "deportivo"
 
urlpatterns = [
    path("entrenamientos/", views.entrenamientos, name="entrenamientos"),
    path(
        "entrenamientos/<int:pk>/asistencia/",
        views.tomar_asistencia,
        name="tomar_asistencia",
    ),
    # HU-06
    path(
        "entrenamientos/<int:pk>/planificacion/",
        views.editar_planificacion,
        name="editar_planificacion",
    ),
    path("calendario/", views.calendario, name="calendario"),
    path(
        "calendario/<int:pk>/eliminar/",
        views.eliminar_evento,
        name="eliminar_evento",
    ),
    path("nominas/", views.nominas, name="nominas"),
    path("nominas/nueva/", views.nueva_nomina, name="nueva_nomina"),
    path("nominas/exportar/", views.exportar_nominas, name="exportar_nominas"), # HU-20
    path("nominas/<int:pk>/", views.ver_nomina, name="ver_nomina"),
    path("nominas/<int:pk>/pdf/", views.nomina_pdf, name="nomina_pdf"),
]