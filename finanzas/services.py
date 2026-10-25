
from calendar import monthrange
from datetime import date

from django.utils import timezone

from .models import Beca, Cuota


MESES_IMPAGOS_PARA_BLOQUEO = 2


def jugador_bloqueado_por_morosidad(jugador, fecha=None):
    """
    Retorna True si el jugador no tiene beca completa y acumula
    dos o más períodos mensuales vencidos e impagos.
    """
    if getattr(jugador, "becado", False):
        return False

    if fecha is None:
        fecha = timezone.localdate()

    cuotas_vencidas = Cuota.objects.filter(
        jugador=jugador,
        estado=Cuota.Estado.PENDIENTE,
        fecha_vencimiento__lt=fecha,
    ).order_by("periodo")

    periodos_impagos = set()

    for cuota in cuotas_vencidas:
        periodos_impagos.add(cuota.periodo)

        if len(periodos_impagos) >= MESES_IMPAGOS_PARA_BLOQUEO:
            return True

    return False
