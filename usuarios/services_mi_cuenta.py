from django.db import transaction

from .models import Usuario
from .services import registrar_auditoria


CAMPOS_EDITABLES_CUENTA = ("first_name", "last_name", "email", "telefono")


@transaction.atomic
def actualizar_datos_cuenta(*, usuario, datos):
    """Actualiza únicamente datos generales de la cuenta autenticada.

    No modifica Jugador ni Apoderado: sus datos de contacto pueden ser
    distintos deliberadamente de los datos generales de Usuario.
    """
    cuenta = Usuario.objects.select_for_update().get(pk=usuario.pk)
    cambios = {}

    for campo in CAMPOS_EDITABLES_CUENTA:
        if campo not in datos:
            continue
        valor = (datos[campo] or "").strip()
        if getattr(cuenta, campo) != valor:
            setattr(cuenta, campo, valor)
            cambios[campo] = valor

    if cambios:
        cuenta.save(update_fields=[*cambios.keys(), "updated_at"])
        registrar_auditoria(
            usuario=cuenta,
            accion="ACTUALIZACION_DATOS_CUENTA",
            entidad="Usuario",
            entidad_id=cuenta.pk,
            detalle={"campos_actualizados": list(cambios.keys())},
        )

    return cuenta
