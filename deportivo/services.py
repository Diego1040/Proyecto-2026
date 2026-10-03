"""Regla de negocio de la asistencia"""

from datetime import datetime, time, timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from usuarios.models import Jugador
from usuarios.services import registrar_auditoria

from .models import Asistencia
from .permisos import es_administracion


PLAZO_EDICION_HORAS = 48

def es_entrenamiento_antiguo(entrenamiento, ahora=None):
    """True si ya paso el plazo para que el entrenador edite."""
    if ahora is None:
        ahora = timezone.localtime()

    fin_del_dia = timezone.make_aware(datetime.combine(entrenamiento.fecha, time.max))
    return ahora > fin_del_dia + timedelta(hours=PLAZO_EDICION_HORAS)

def puede_modificar(usuario, entrenamiento):
    """El entrenador edita dentro del plazo; Administracion siempre puede."""
    if es_administracion(usuario):
        return True
    return not es_entrenamiento_antiguo(entrenamiento)

def jugadores_del_entrenamiento(entrenamiento):
    """Devuelve los jugadores que pueden asistir a un entrenamiento."""
    return (Jugador.objects.filter(categoria_actual=entrenamiento.categoria, estado=Jugador.Estado.ACTIVO).order_by('nombres', 'apellidos'))

@transaction.atomic
def registrar_asistencia(*, entrenamiento, usuario, estados, motivo=""):
    """
    Guarda la asistencia de los jugadores a un entrenamiento.
    
    estados: diccionario {jugador_id: estado}
    """
    if not puede_modificar(usuario, entrenamiento):
        raise ValidationError(f"Pasaron mas de {PLAZO_EDICION_HORAS} horas desde el entrenamiento, Solo los administradores pueden modificar.")

    antiguo = es_entrenamiento_antiguo(entrenamiento)

    if antiguo and not motivo.strip():
        raise ValidationError("Para modificar un entrenamiento antiguo, debe indicar un motivo.")

    validos = set(Asistencia.Estado.values)
    jugadores = {
        j.pk: j for j in jugadores_del_entrenamiento(entrenamiento)
    }

    guardadas = 0

    for jugador_id, estado in estados.items():
        if estado not in validos:
            raise ValidationError("Estado de asistencia invalido.")

        jugador = jugadores.get(jugador_id)
        if jugador is None:
            continue

        Asistencia.objects.update_or_create(
            entrenamiento=entrenamiento,
            jugador=jugador,
            defaults={
                'estado': estado,
                'registrado_por': usuario,
                'motivo_modificacion': motivo if antiguo else "",
            },
        )

        guardadas += 1

    if antiguo:
        registrar_auditoria(
            usuario=usuario,
            accion="ASISTENCIA_MODIFICADA_FUERA_DE_PLAZO",
            entidad="Entrenamiento",
            entidad_id=entrenamiento.pk,
            detalle={"motivo": motivo.strip(), "jugadores": guardadas},
        )

    return guardadas