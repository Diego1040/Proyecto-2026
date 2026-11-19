from django.urls import path

from . import views

app_name = "institucional"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("documentos/", views.documentos, name="documentos"),
    path("documentos/nuevo/", views.documento_nuevo, name="documento_nuevo"),
    path("documentos/<int:pk>/", views.documento_detalle, name="documento_detalle"),
    path("documentos/<int:pk>/versiones/nueva/", views.documento_version, name="documento_version_nueva"),
    path("documentos/versiones/<int:version_id>/editar/", views.documento_version, name="documento_editar"),
    path("documentos/versiones/<int:version_id>/publicar/", views.documento_publicar, name="documento_publicar"),
    path("documentos/versiones/<int:version_id>/descargar/", views.documento_descargar, name="documento_descargar"),
    path("miembros/", views.miembros, name="miembros"),
    path("actas/", views.actas, name="actas"),
    path("actas/nueva/", views.acta_nueva, name="acta_nueva"),
    path("actas/<int:pk>/", views.acta_detalle, name="acta_detalle"),
    path("actas/<int:pk>/versiones/nueva/", views.acta_version, name="acta_version_nueva"),
    path("actas/versiones/<int:version_id>/editar/", views.acta_version, name="acta_editar"),
    path("actas/versiones/<int:version_id>/publicar/", views.acta_publicar, name="acta_publicar"),
    path("actas/versiones/<int:version_id>/descargar/", views.acta_descargar, name="acta_descargar"),
    path("comite/", views.sanciones, name="sanciones"),
    path("comite/nueva/", views.sancion_nueva, name="sancion_nueva"),
    path("comite/<int:pk>/", views.sancion_detalle, name="sancion_detalle"),
    path("comite/<int:pk>/corregir/", views.sancion_accion, {"accion": "corregir"}, name="sancion_corregir"),
    path("comite/<int:pk>/resolver/", views.sancion_accion, {"accion": "resolver"}, name="sancion_resolver"),
    path("comite/<int:pk>/anular/", views.sancion_accion, {"accion": "anular"}, name="sancion_anular"),
]
