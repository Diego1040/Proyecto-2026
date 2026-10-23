
from calendar import monthrange
from datetime import date

from django.utils import timezone

from .models import Beca, Cuota


MESES_IMPAGOS_PARA_BLOQUEO = 2


def jugador_bloqueado_por_morosidad(jugador, fecha=None):
    """
    Retorna True cuando un jugador acumula dos o más
    mensualidades vencidas e impagas, excluyendo períodos
    cubiertos por una beca completa registrada.
    """
    if fecha is None:
        fecha = timezone.localdate()

    cuotas_vencidas = Cuota.objects.filter(
        jugador=jugador,
        estado=Cuota.Estado.PENDIENTE,
        fecha_vencimiento__lt=fecha,
    ).order_by("periodo")

    periodos_impagos = set()

    for cuota in cuotas_vencidas:
        ultimo_dia = monthrange(
            cuota.periodo.year,
            cuota.periodo.month,
        )[1]

        fin_periodo = date(
            cuota.periodo.year,
            cuota.periodo.month,
            ultimo_dia,
        )

        periodo_cubierto_por_beca = Beca.objects.filter(
            jugador=jugador,
            fecha_inicio__lte=fin_periodo,
            fecha_termino__gte=cuota.periodo,
        ).exists()

        if periodo_cubierto_por_beca:
            continue

        periodos_impagos.add(cuota.periodo)

        if len(periodos_impagos) >= MESES_IMPAGOS_PARA_BLOQUEO:
            return True

    return False
