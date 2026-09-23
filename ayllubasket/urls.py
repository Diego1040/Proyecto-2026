"""
URLs del proyecto Ayllu Basket.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),

    # login, logout y cambio de contrasena de Django
    path("cuentas/", include("django.contrib.auth.urls")),

    path("", include("usuarios.urls")),
]
