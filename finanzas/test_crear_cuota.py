from datetime import date
from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from usuarios.models import Jugador, PeriodoInactividad, Usuario

from .models import Beca, Cuota, Pago


class CrearCuotaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tesorero = Usuario.objects.create_user(rut="12345678-5")
        cls.tesorero.groups.add(Group.objects.create(name="Tesorería"))
        cls.admin = Usuario.objects.create_superuser(rut="22222222-2", password="clave-de-prueba")
        cls.jugador = Jugador.objects.create(
            rut="11111111-1", nombres="Jugador", apellidos="Prueba",
            fecha_nacimiento=date(2010, 5, 1), rama="VARONES", estado="ACTIVO",
        )

    def setUp(self):
        self.client.force_login(self.tesorero)
        self.url = reverse("finanzas:crear_cuota")

    def datos(self, periodo):
        return {"jugador": self.jugador.pk, "concepto": "Mensualidad de prueba",
                "periodo": periodo, "monto": 15000, "fecha_vencimiento": periodo + "-20"}

    def test_formulario_creacion_y_duplicado(self):
        pagina = self.client.get(self.url)
        for nombre in (*self.datos("2025-02"), "csrfmiddlewaretoken"):
            self.assertContains(pagina, f'name="{nombre}"')
        datos = self.datos("2025-02")
        self.assertRedirects(self.client.post(self.url, datos), reverse("finanzas:tesoreria"))
        cuota = Cuota.objects.get()
        self.assertEqual((cuota.periodo, cuota.estado), (date(2025, 2, 1), Cuota.Estado.PENDIENTE))
        duplicado = self.client.post(self.url, datos)
        self.assertTrue(duplicado.context["form"].errors)
        self.assertEqual(Cuota.objects.count(), 1)
        self.assertFalse(Pago.objects.exists())

    def test_requiere_tesoreria(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.datos("2025-02")).status_code, 403)
        self.assertFalse(Cuota.objects.exists())

    def test_beca_superpuesta_se_rechaza_y_mes_posterior_se_admite(self):
        Beca.objects.create(jugador=self.jugador, fecha_inicio=date(2025, 1, 16))
        for periodo in ("2025-01", "2025-07"):
            respuesta = self.client.post(self.url, self.datos(periodo))
            self.assertFormError(respuesta.context["form"], "periodo",
                                 "Una beca cubre esta mensualidad. Elige otro período.")
        self.assertFalse(Cuota.objects.exists())
        self.assertEqual(self.client.post(self.url, self.datos("2025-08")).status_code, 302)

    def test_beca_finalizada_respeta_el_mismo_limite_que_el_generador(self):
        Beca.objects.create(jugador=self.jugador, fecha_inicio=date(2025, 1, 1),
                            estado=Beca.Estado.FINALIZADA, fecha_finalizacion=date(2025, 3, 12))
        for periodo in ("2025-02", "2025-03"):
            call_command("generar_cuotas_mensuales", periodo=periodo, stdout=StringIO())
        self.assertEqual(list(Cuota.objects.values_list("periodo", flat=True)), [date(2025, 3, 1)])
        self.assertIn("periodo", self.client.post(self.url, self.datos("2025-02")).context["form"].errors)
        self.assertEqual(self.client.post(self.url, self.datos("2025-04")).status_code, 302)

    def test_receso_congela_meses_hasta_la_reactivacion_inclusive(self):
        receso = PeriodoInactividad.objects.create(
            jugador=self.jugador, motivo="RECESO_PERSONAL", fecha_inicio=date(2025, 2, 15),
        )
        mensaje = "La mensualidad está congelada por inactividad en este período."
        self.assertFormError(self.client.post(self.url, self.datos("2025-04")).context["form"], "periodo", mensaje)
        receso.fecha_reactivacion = date(2025, 3, 1)
        receso.save()
        for periodo in ("2025-02", "2025-03"):
            self.assertFormError(self.client.post(self.url, self.datos(periodo)).context["form"], "periodo", mensaje)
        self.assertFalse(Cuota.objects.exists())
        self.assertEqual(self.client.post(self.url, self.datos("2025-04")).status_code, 302)

    def test_admin_rechaza_ambas_exclusiones_y_admite_una_mensualidad_libre(self):
        self.client.force_login(self.admin)
        Beca.objects.create(jugador=self.jugador, fecha_inicio=date(2025, 1, 1))
        PeriodoInactividad.objects.create(jugador=self.jugador, motivo="LESION", fecha_inicio=date(2025, 8, 1))
        url = reverse("admin:finanzas_cuota_add")
        for periodo, ok in (("2025-01", False), ("2025-08", False), ("2025-07", True)):
            datos = dict(self.datos(periodo), periodo=periodo + "-01", estado="PENDIENTE")
            respuesta = self.client.post(url, datos)
            if ok:
                self.assertEqual(respuesta.status_code, 302)
            else:
                self.assertIn("periodo", respuesta.context["adminform"].form.errors)
        self.assertEqual(list(Cuota.objects.values_list("periodo", flat=True)), [date(2025, 7, 1)])

    def test_cobertura_posterior_preserva_cuota_historica_y_pago(self):
        cuota = Cuota.objects.create(jugador=self.jugador, periodo=date(2025, 1, 1),
                                     fecha_vencimiento=date(2025, 1, 20), monto=15000, estado="PAGADA")
        pago = Pago.objects.create(cuota=cuota, usuario=self.tesorero, monto=cuota.monto,
                                   estado="CONFIRMADO", medio_pago="TRANSFERENCIA")
        Beca.objects.create(jugador=self.jugador, fecha_inicio=date(2025, 1, 1))
        cuota.full_clean()
        self.client.post(self.url, self.datos("2025-01"))
        cuota.refresh_from_db()
        pago.refresh_from_db()
        self.assertEqual((cuota.estado, cuota.monto, pago.estado, pago.monto), ("PAGADA", 15000, "CONFIRMADO", 15000))
        self.assertEqual(Cuota.objects.count(), 1)
