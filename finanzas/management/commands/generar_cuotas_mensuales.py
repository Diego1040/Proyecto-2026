
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from finanzas.models import Beca, Cuota
from usuarios.models import Jugador


# Valor provisional mientras se define la tarifa oficial.
MONTO_CUOTA_MENSUAL = Decimal("15000")  # CLP

# Vencimiento provisional: día 10 de cada mes.
DIA_VENCIMIENTO = 10


class Command(BaseCommand):
    help = "Genera las cuotas mensuales de los jugadores activos sin beca."

    def add_arguments(self, parser):
        parser.add_argument(
            "--periodo",
            type=str,
            help=(
                "Período que se generará en formato AAAA-MM. "
                "Por defecto utiliza el mes actual."
            ),
        )

        parser.add_argument(
            "--simular",
            action="store_true",
            help="Calcula las cuotas sin guardarlas en la base de datos.",
        )

    def handle(self, *args, **options):
        periodo_indicado = options.get("periodo")

        if periodo_indicado:
            try:
                periodo = datetime.strptime(
                    periodo_indicado,
                    "%Y-%m",
                ).date().replace(day=1)
            except ValueError as exc:
                raise CommandError(
                    "El período debe tener formato AAAA-MM, "
                    "por ejemplo 2026-10."
                ) from exc
        else:
            hoy = timezone.localdate()
            periodo = date(hoy.year, hoy.month, 1)

        ultimo_dia = monthrange(
            periodo.year,
            periodo.month,
        )[1]

        fecha_vencimiento = date(
            periodo.year,
            periodo.month,
            min(DIA_VENCIMIENTO, ultimo_dia),
        )

        # Solo jugadores activos que no tengan beca completa.
        # Calcular el último día del período.
        fin_periodo = date(
            periodo.year,
            periodo.month,
            ultimo_dia,
        )

        # Buscar becas activas que cubran el período.
        becas_del_periodo = Beca.objects.filter(
            jugador_id=OuterRef("pk"),
            estado=Beca.Estado.ACTIVA,
            fecha_inicio__lte=fin_periodo,
            fecha_termino__gte=periodo,
        )

        # Seleccionar jugadores activos sin beca en el período.
        jugadores = (
            Jugador.objects.filter(
                estado=Jugador.Estado.ACTIVO,
            )
            .annotate(
                tiene_beca_en_periodo=Exists(becas_del_periodo),
            )
            .filter(
                tiene_beca_en_periodo=False,
            )
            .order_by("pk")
        )

        # Modo de simulación: consulta, calcula y termina sin guardar.
        if options.get("simular"):
            total_elegibles = jugadores.count()

            existentes = Cuota.objects.filter(
                jugador__in=jugadores,
                periodo=periodo,
            ).count()

            por_generar = total_elegibles - existentes

            self.stdout.write(
                f"Simulación del período: {periodo:%Y-%m}\n"
                f"Jugadores activos sin beca: {total_elegibles}\n"
                f"Cuotas existentes para esos jugadores: {existentes}\n"
                f"Cuotas que se crearían: {por_generar}\n"
                f"Monto potencial: "
                f"${por_generar * MONTO_CUOTA_MENSUAL:,.0f} CLP\n"
                f"Vencimiento provisional: "
                f"{fecha_vencimiento:%d/%m/%Y}"
            )
            return

        creadas = 0
        ya_existentes = 0

        with transaction.atomic():
            for jugador in jugadores.iterator():
                _, creada = Cuota.objects.get_or_create(
                    jugador=jugador,
                    periodo=periodo,
                    defaults={
                        "concepto": "Cuota mensual",
                        "monto": MONTO_CUOTA_MENSUAL,
                        "fecha_vencimiento": fecha_vencimiento,
                    },
                )

                if creada:
                    creadas += 1
                else:
                    ya_existentes += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Período procesado: {periodo:%Y-%m}\n"
                f"Monto por cuota: ${MONTO_CUOTA_MENSUAL:,.0f} CLP\n"
                f"Vencimiento provisional: "
                f"{fecha_vencimiento:%d/%m/%Y}\n"
                f"Cuotas creadas: {creadas}\n"
                f"Cuotas que ya existían: {ya_existentes}"
            )
        )
