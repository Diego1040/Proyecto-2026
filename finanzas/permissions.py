
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def tesoreria_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        autorizado = request.user.groups.filter(
            name="Tesorería"
        ).exists()

        if not autorizado:
            raise PermissionDenied(
                "No tienes permiso para acceder a Tesorería."
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def becas_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        autorizado = request.user.groups.filter(
            name__in=("Tesorería", "Administración")
        ).exists()

        if not autorizado:
            raise PermissionDenied(
                "No tienes permiso para gestionar becas."
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view
