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
    # NUEVO HU-06
    path(
        "entrenamientos/<int:pk>/planificacion/",
        views.editar_planificacion,
        name="editar_planificacion",
    ),
]