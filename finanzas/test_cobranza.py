from datetime import date, timedelta
from uuid import uuid4

from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import Jugador, Usuario
from .models import AvisoCobranza, Cuota, Pago


class SeguimientoCobranzaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tesorera = Usuario.objects.create_user(rut="12345678-5", first_name="Tesorera ficticia")
        cls.tesorera.groups.add(Group.objects.create(name="Tesorería"))
        cls.admin = Usuario.objects.create_user(rut="22222222-2", is_staff=True)
        cls.admin.groups.add(Group.objects.get_or_create(name="Administración")[0])
        cls.jugador, cls.otro = [
            Jugador.objects.create(
                rut=rut, nombres=nombre, apellidos="Ejemplo", fecha_nacimiento=date(2010, 1, 1),
                rama="VARONES", estado="ACTIVO",
            ) for rut, nombre in [("11111111-1", "Mario"), ("33333333-3", "Ema")]
        ]

    def setUp(self):
        self.client.force_login(self.tesorera)
        self.panel = reverse("finanzas:tesoreria")
        self.url = reverse("finanzas:cobranza_jugador", query={"jugador": self.jugador.pk})
        self.datos = {
            "fecha_aviso": timezone.localdate(), "medio": "Teléfono", "destinatario": "Familia ficticia",
            "detalle": "Se conversó sobre las cuotas pendientes.", "clave_registro": uuid4(),
        }

    def test_registro_desde_alerta_y_consulta_despues_de_regularizar(self):
        for mes in [1, 2]:
            Cuota.objects.create(jugador=self.jugador, periodo=date(2025, mes, 1), monto=15000,
                                 fecha_vencimiento=date(2025, mes, 15))
        self.assertContains(self.client.get(self.panel), f'href="{self.url}"')
        inicial = self.client.get(self.url)
        self.assertContains(inicial, "Aún no hay avisos")
        self.datos["clave_registro"] = inicial.context["form"]["clave_registro"].value()
        self.assertRedirects(self.client.post(self.url, {**self.datos, "responsable": self.admin.pk}), self.url)
        aviso = AvisoCobranza.objects.get()
        self.assertEqual((aviso.jugador, aviso.responsable, aviso.fecha_aviso),
                         (self.jugador, self.tesorera, self.datos["fecha_aviso"]))
        self.assertEqual(Cuota.objects.filter(estado=Cuota.Estado.PENDIENTE).count(), 2)
        self.assertFalse(Pago.objects.exists())

        # La alerta desaparece al regularizar. El acceso desde el selector debe seguir disponible.
        Cuota.objects.update(estado=Cuota.Estado.PAGADA)
        panel = self.client.get(self.panel)
        self.assertContains(panel, "No hay jugadores en morosidad crítica")
        self.assertContains(panel, f'action="{reverse("finanzas:cobranza_jugador")}"')
        self.assertContains(panel, f'<option value="{self.jugador.pk}">')
        otra_sesion = Client()
        otra_sesion.force_login(self.tesorera)
        historial = otra_sesion.get(self.url)
        for texto in ["Tesorera ficticia", "Teléfono", "Familia ficticia", self.datos["detalle"]]:
            self.assertContains(historial, texto)
        ajeno = otra_sesion.get(reverse("finanzas:cobranza_jugador"), {"jugador": self.otro.pk})
        self.assertNotContains(ajeno, self.datos["detalle"])

    def test_reintento_no_duplica_y_otra_gestion_conserva_ambas_en_orden(self):
        for _ in range(2):
            self.assertRedirects(self.client.post(self.url, self.datos), self.url)
        self.assertEqual(AvisoCobranza.objects.count(), 1)
        self.client.post(self.url, {**self.datos, "fecha_aviso": timezone.localdate() - timedelta(days=1),
                                    "medio": "Correo", "clave_registro": uuid4()})
        historial = self.client.get(self.url).context["historial"]
        self.assertEqual([a.medio for a in historial], ["Teléfono", "Correo"])

    def test_rechaza_fecha_futura_y_datos_incompletos(self):
        respuesta = self.client.post(self.url, {
            **self.datos, "fecha_aviso": timezone.localdate() + timedelta(days=1), "destinatario": " ",
        })
        self.assertFormError(respuesta.context["form"], "fecha_aviso", "La fecha del aviso no puede ser futura.")
        self.assertIn("destinatario", respuesta.context["form"].errors)
        self.assertFalse(AvisoCobranza.objects.exists())

    def test_consulta_y_registro_exigen_tesoreria_incluso_por_url_directa(self):
        self.client.logout()
        for metodo in [self.client.get, self.client.post]:
            self.assertEqual(metodo(self.url).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)
        self.assertFalse(AvisoCobranza.objects.exists())

    def test_jugador_inexistente_y_post_sin_csrf_no_registran(self):
        sin_jugador = reverse("finanzas:cobranza_jugador", query={"jugador": 99999})
        self.assertEqual(self.client.post(sin_jugador, self.datos).status_code, 404)
        estricto = Client(enforce_csrf_checks=True)
        estricto.force_login(self.tesorera)
        self.assertEqual(estricto.post(self.url, self.datos).status_code, 403)
        self.assertFalse(AvisoCobranza.objects.exists())
