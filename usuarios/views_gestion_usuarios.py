"""Vistas de consulta para la administración de cuentas de usuario.

Esta primera etapa es deliberadamente de solo lectura: no modifica cuentas,
perfiles, contraseñas ni grupos.
"""
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, render

from .models import Usuario


ROLES_INSTITUCIONALES = (
    "Administración",
    "Secretaría",
    "Comité de Disciplina",
    "Tesorería",
    "Entrenador",
)
USUARIOS_POR_PAGINA = 25


def _consulta_usuarios():
    """Prepara cuentas y relaciones sin alterar ningún dato."""
    grupos_funcionales = Group.objects.filter(
        name__in=ROLES_INSTITUCIONALES,
    ).order_by("name")

    usuarios = (
        Usuario.objects
        .select_related("jugador", "apoderado")
        .prefetch_related(
            Prefetch(
                "groups",
                queryset=Group.objects.filter(name__in=ROLES_INSTITUCIONALES),
                to_attr="grupos_funcionales",
            )
        )
        .order_by("rut")
    )
    return usuarios, grupos_funcionales


@login_required
@permission_required("usuarios.view_usuario", raise_exception=True)
def listado_usuarios(request):
    """Lista todas las cuentas, incluidas las que no tienen perfil asociado."""
    usuarios, grupos = _consulta_usuarios()

    busqueda = request.GET.get("q", "").strip()[:100]
    estado = request.GET.get("estado", "").strip()
    grupo_seleccionado = request.GET.get("grupo", "").strip()

    if busqueda:
        usuarios = usuarios.filter(
            Q(rut__icontains=busqueda)
            | Q(email__icontains=busqueda)
            | Q(first_name__icontains=busqueda)
            | Q(last_name__icontains=busqueda)
            | Q(jugador__nombres__icontains=busqueda)
            | Q(jugador__apellidos__icontains=busqueda)
            | Q(apoderado__nombres__icontains=busqueda)
            | Q(apoderado__apellidos__icontains=busqueda)
        )

    if estado == "activa":
        usuarios = usuarios.filter(is_active=True)
    elif estado == "inactiva":
        usuarios = usuarios.filter(is_active=False)
    else:
        estado = ""

    ids_grupos_disponibles = set(grupos.values_list("pk", flat=True))
    if grupo_seleccionado.isdigit() and int(grupo_seleccionado) in ids_grupos_disponibles:
        usuarios = usuarios.filter(groups__pk=int(grupo_seleccionado))
    else:
        grupo_seleccionado = ""

    usuarios = usuarios.distinct()
    total_usuarios = usuarios.count()
    pagina = Paginator(usuarios, USUARIOS_POR_PAGINA).get_page(
        request.GET.get("page")
    )

    return render(
        request,
        "usuarios/gestion_usuarios_listado.html",
        {
            "page_obj": pagina,
            "grupos": grupos,
            "busqueda": busqueda,
            "estado": estado,
            "grupo_seleccionado": grupo_seleccionado,
            "total_usuarios": total_usuarios,
        },
    )


@login_required
@permission_required("usuarios.view_usuario", raise_exception=True)
def detalle_usuario(request, pk):
    """Muestra información básica y de solo lectura de una cuenta."""
    usuarios, _ = _consulta_usuarios()
    usuario = get_object_or_404(usuarios, pk=pk)
    return render(
        request,
        "usuarios/gestion_usuarios_detalle.html",
        {"cuenta": usuario},
    )
