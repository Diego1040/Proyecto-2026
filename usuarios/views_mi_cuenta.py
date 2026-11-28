from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms_mi_cuenta import MiCuentaForm
from .models import Usuario
from .services_mi_cuenta import actualizar_datos_cuenta


@login_required

def editar_mi_cuenta(request):
    """Permite a cualquier usuario autenticado editar exclusivamente su cuenta."""
    cuenta = Usuario.objects.get(pk=request.user.pk)

    if request.method == "POST":
        form = MiCuentaForm(request.POST, instance=cuenta)
        if form.is_valid():
            actualizar_datos_cuenta(
                usuario=request.user,
                datos=form.cleaned_data,
            )
            messages.success(
                request,
                "Tus datos generales se actualizaron correctamente.",
            )
            return redirect("editar_mi_cuenta")
    else:
        form = MiCuentaForm(instance=cuenta)

    return render(
        request,
        "usuarios/mi_cuenta.html",
        {
            "form": form,
            "cuenta": cuenta,
        },
    )
