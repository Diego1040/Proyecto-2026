"""
Reglas de acceso de la app deportivo.

Los roles se manejan con grupos de Django, igual que
es_administracion() en usuarios/views.py.
"""

from usuarios.models import Categoria

GRUPO_ENTRENADOR = 'Entrenador'
GRUPO_ADMINISTRADOR = 'Administrador'

def es_entrenador(usuario):
    return (usuario.is_authenticated and usuario.groups.filter(name=GRUPO_ENTRENADOR).exists())

def es_administrador(usuario):
    return (usuario.is_authenticated and usuario.groups.filter(name=GRUPO_ADMINISTRADOR).exists())

def categorias_visibles(usuario):
    """
    Categorias cuya asistencia puede ver y registrar el usuario.
    
    - Administracion: todas las activas.
    - Entrenador: solo las que tiene asignadas.
    - Culquier otro usuario: ninguna.
    """

    if es_administrador(usuario):
        return Categoria.objects.filter(activa=True)
    
    if es_entrenador(usuario) and hasattr(usuario, 'perfil_entrenador'):
        return usuario.perfil_entrenador.categorias.filter(activa=True)

    return Categoria.objects.none()