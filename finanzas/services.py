
from calendar import monthrange
from datetime import date

from django.utils import timezone

from .models import Beca, Cuota

from django.db.models import Count, Exists, OuterRef, Q, Sum
from usuarios.models import Jugador, PeriodoInactividad


MESES_IMPAGOS_PARA_BLOQUEO = 2



def jugadores_con_cobertura_mensual(periodo):
    """Anota los períodos de beca e inactividad que usa el cobro mensual."""
    inicio = periodo.replace(day=1)
    fin = periodo.replace(day=monthrange(periodo.year, periodo.month)[1])
    becas = Beca.objects.filter(
        jugador_id=OuterRef("pk"), fecha_inicio__lte=fin, fecha_termino__gte=inicio,
    ).filter(
        Q(estado__in=[Beca.Estado.ACTIVA, Beca.Estado.RENOVADA])
        | Q(estado=Beca.Estado.FINALIZADA, fecha_finalizacion__gt=fin)
    )
    inactividades = PeriodoInactividad.objects.filter(
        jugador_id=OuterRef("pk"), fecha_inicio__lte=fin,
    ).filter(Q(fecha_reactivacion__isnull=True) | Q(fecha_reactivacion__gte=inicio))
    return Jugador.objects.annotate(
        tiene_beca_en_periodo=Exists(becas),
        tiene_inactividad_en_periodo=Exists(inactividades),
    )


def jugador_bloqueado_por_morosidad(jugador, fecha=None):
    """
    Retorna True si el jugador no tiene una beca completa vigente
    y acumula dos o más períodos mensuales vencidos e impagos.

    Las becas tienen una duración de seis meses y su vigencia
    se determina mediante los registros de Tesorería.
    """
    if fecha is None:
        fecha = timezone.localdate()

    # Comprobar si el jugador tiene alguna beca vigente.
    becas = Beca.objects.filter(
        jugador=jugador
    ).only(
        "fecha_inicio",
        "fecha_termino",
        "fecha_finalizacion",
        "estado",
    )

    if any(beca.vigente_en(fecha) for beca in becas):
        return False

    # Buscar cuotas vencidas que continúan pendientes.
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


def obtener_resumen_morosidad(fecha=None):
    """
    Obtiene los jugadores con dos o más períodos vencidos e impagos,
    excluyendo a quienes tienen una beca completa vigente.
    """
    if fecha is None:
        fecha = timezone.localdate()

    # Agrupar las cuotas vencidas por jugador.
    resumenes = list(
        Cuota.objects.filter(
            estado=Cuota.Estado.PENDIENTE,
            fecha_vencimiento__lt=fecha,
        )
        .values("jugador_id")
        .annotate(
            meses_impagos=Count("periodo", distinct=True),
            deuda_vencida=Sum("monto"),
        )
        .filter(
            meses_impagos__gte=MESES_IMPAGOS_PARA_BLOQUEO
        )
        .order_by("-meses_impagos", "-deuda_vencida")
    )

    if not resumenes:
        return []

    # Identificar las becas que realmente están vigentes.
    becas_candidatas = Beca.objects.filter(
        fecha_inicio__lte=fecha,
        fecha_termino__gte=fecha,
    ).only(
        "jugador_id",
        "fecha_inicio",
        "fecha_termino",
        "fecha_finalizacion",
        "estado",
    )

    jugadores_con_beca = {
        beca.jugador_id
        for beca in becas_candidatas
        if beca.vigente_en(fecha)
    }

    # Excluir jugadores con beca completa vigente.
    resumenes = [
        registro
        for registro in resumenes
        if registro["jugador_id"] not in jugadores_con_beca
    ]

    if not resumenes:
        return []

    # Recuperar los datos de los jugadores en una consulta.
    jugadores = Jugador.objects.filter(
        pk__in=[registro["jugador_id"] for registro in resumenes]
    ).select_related("categoria_actual").in_bulk()

    return [
        {
            "jugador": jugadores[registro["jugador_id"]],
            "meses_impagos": registro["meses_impagos"],
            "deuda_vencida": registro["deuda_vencida"],
        }
        for registro in resumenes
        if registro["jugador_id"] in jugadores
    ]
