"""
URLs del proyecto Ayllu Basket.
"""
from django.contrib import admin
from django.urls import include, path
from usuarios.views import ConfirmarRecuperacionView

urlpatterns = [
    path("admin/", admin.site.urls),

    path(
        "cuentas/reset/<uidb64>/<token>/",
        ConfirmarRecuperacionView.as_view(),
        name="password_reset_confirm",
    ),

    # login, logout y cambio de contrasena de Django
    path("cuentas/", include("django.contrib.auth.urls")),

    path("", include("usuarios.urls")),
]
