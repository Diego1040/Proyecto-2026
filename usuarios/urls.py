from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("panel/", views.panel, name="panel"),
    path(
        "administracion/fichas/",
        views.validar_fichas,
        name="validar_fichas",
    ),
]
