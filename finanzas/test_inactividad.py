from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from usuarios.models import Jugador, PeriodoInactividad
from .models import Cuota


class CongelacionCuotasTests(TestCase):
    def setUp(self):
        self.jugador = Jugador.objects.create(
            rut="23456789-6",
            nombres="Jugador",
            apellidos="De Prueba",
            fecha_nacimiento=date(2012, 3, 15),
            rama=Jugador.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO,
        )

    def generar_cuotas(self, periodo):
        call_command(
            "generar_cuotas_mensuales",
            periodo=periodo,
            stdout=StringIO(),
            verbosity=0,
        )

    def test_inactividad_congela_meses_y_reactivacion_reanuda(self):
        inactividad = PeriodoInactividad.objects.create(
            jugador=self.jugador,
            motivo=PeriodoInactividad.Motivo.LESION,
            fecha_inicio=date(2026, 8, 10),
            observaciones="Lesión de prueba",
        )

        self.jugador.refresh_from_db()
        self.assertEqual(
            self.jugador.estado,
            Jugador.Estado.INACTIVO,
        )

        # Agosto queda congelado.
        self.generar_cuotas("2026-08")
        self.assertFalse(
            Cuota.objects.filter(
                jugador=self.jugador,
                periodo=date(2026, 8, 1),
            ).exists()
        )

        # Reincorporación manual el 15 de septiembre.
        inactividad.fecha_reactivacion = date(2026, 9, 15)
        inactividad.save()

        self.jugador.refresh_from_db()
        self.assertEqual(
            self.jugador.estado,
            Jugador.Estado.ACTIVO,
        )

        # Septiembre también queda congelado.
        self.generar_cuotas("2026-09")
        self.assertFalse(
            Cuota.objects.filter(
                jugador=self.jugador,
                periodo=date(2026, 9, 1),
            ).exists()
        )

        # Octubre vuelve a generar una cuota.
        self.generar_cuotas("2026-10")

        cuota_octubre = Cuota.objects.get(
            jugador=self.jugador,
            periodo=date(2026, 10, 1),
        )

        self.assertEqual(cuota_octubre.monto, Decimal("15000"))

    def test_la_inactividad_no_elimina_una_cuota_existente(self):
        cuota = Cuota.objects.create(
            jugador=self.jugador,
            concepto="Cuota mensual",
            periodo=date(2026, 8, 1),
            monto=Decimal("15000"),
            fecha_vencimiento=date(2026, 8, 10),
            estado=Cuota.Estado.PENDIENTE,
        )

        PeriodoInactividad.objects.create(
            jugador=self.jugador,
            motivo=PeriodoInactividad.Motivo.RECESO_PERSONAL,
            fecha_inicio=date(2026, 8, 10),
        )

        self.generar_cuotas("2026-08")

        cuota.refresh_from_db()

        self.assertEqual(cuota.estado, Cuota.Estado.PENDIENTE)
        self.assertEqual(cuota.monto, Decimal("15000"))
        self.assertTrue(
            Cuota.objects.filter(pk=cuota.pk).exists()
        )

    
    def test_reactivacion_el_primer_dia_del_mes_congela_ese_mes(self):
        inactividad = PeriodoInactividad.objects.create(
            jugador=self.jugador,
            motivo=PeriodoInactividad.Motivo.LESION,
            fecha_inicio=date(2026, 8, 10),
        )

        inactividad.fecha_reactivacion = date(2026, 9, 1)
        inactividad.save()

        self.jugador.refresh_from_db()
        self.assertEqual(
            self.jugador.estado,
            Jugador.Estado.ACTIVO,
        )

        self.generar_cuotas("2026-09")

        self.assertFalse(
            Cuota.objects.filter(
                jugador=self.jugador,
                periodo=date(2026, 9, 1),
            ).exists()
        )

        self.generar_cuotas("2026-10")

        self.assertTrue(
            Cuota.objects.filter(
                jugador=self.jugador,
                periodo=date(2026, 10, 1),
            ).exists()
        )

    def test_generar_dos_veces_no_duplica_cuotas(self):
        inactividad = PeriodoInactividad.objects.create(
            jugador=self.jugador,
            motivo=PeriodoInactividad.Motivo.LESION,
            fecha_inicio=date(2026, 8, 10),
        )

        inactividad.fecha_reactivacion = date(2026, 9, 15)
        inactividad.save()

        self.generar_cuotas("2026-10")
        self.generar_cuotas("2026-10")

        self.assertEqual(
            Cuota.objects.filter(
                jugador=self.jugador,
                periodo=date(2026, 10, 1),
            ).count(),
            1,
        )
