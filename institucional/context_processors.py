from . import permisos


def accesos_institucionales(request):
    accesos = {
        "normativa": permisos.puede_consultar_normativa(request.user),
        "gestionar_normativa": permisos.puede_gestionar_normativa(request.user),
        "publicar_normativa": permisos.puede_publicar_normativa(request.user),
        "miembros": permisos.puede_gestionar_miembros(request.user),
        "actas": permisos.puede_consultar_actas(request.user),
        "gestionar_actas": permisos.puede_gestionar_actas(request.user),
        "publicar_actas": permisos.puede_publicar_actas(request.user),
        "comite": permisos.puede_consultar_sanciones(request.user),
        "registrar_sanciones": permisos.puede_registrar_sanciones(request.user),
        "corregir_sanciones": permisos.puede_corregir_sanciones(request.user),
        "resolver_sanciones": permisos.puede_resolver_sanciones(request.user),
    }
    perfiles = []
    if accesos["gestionar_actas"]:
        perfiles.append("Secretaría")
    if accesos["comite"]:
        perfiles.append("Comité de Disciplina")
    disponible = any(accesos.values())
    return {"institucional_accesos": accesos, "institucional_disponible": disponible,
            "institucional_perfiles": perfiles,
            "institucional_acceso_tesoreria": disponible and request.user.groups.filter(name="Tesorería").exists()}
