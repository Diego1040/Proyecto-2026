from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def inicio(request):
    """Portada publica del club."""
    return render(request, "paginas/inicio.html")


@login_required
def panel(request):
    """
    Destino provisional despues del login.

    Cuando existan las vistas por rol (apoderado, entrenador,
    tesoreria, administracion) esta vista debe redirigir a la
    que corresponda segun el perfil del usuario.
    """
    usuario = request.user

    if usuario.is_staff:
        perfil = "Administracion"
    elif hasattr(usuario, "apoderado"):
        perfil = "Apoderado"
    elif hasattr(usuario, "jugador"):
        perfil = "Jugador"
    else:
        perfil = "Sin perfil asignado"

    return render(request, "paginas/panel.html", {"perfil": perfil})
