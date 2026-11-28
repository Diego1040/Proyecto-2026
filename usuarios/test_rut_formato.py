from django.test import TestCase
from django.urls import reverse

from .forms import InscripcionJugadorForm, SolicitudActivacionForm


class RutFormatoFrontendTest(TestCase):
    """El RUT se formatea en el navegador (rut.js) y se valida en el servidor."""

    def test_pantallas_con_rut_cargan_el_formateador(self):
        for nombre in ("inscripcion", "login", "activar_cuenta"):
            with self.subTest(pantalla=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertContains(respuesta, "js/rut.js")
                self.assertContains(respuesta, "data-rut")

    def test_campos_rut_tienen_ejemplo_con_puntos(self):
        form = InscripcionJugadorForm()
        for campo in ("rut", "rut_apoderado"):
            html = str(form[campo])
            self.assertIn("data-rut", html)
            self.assertIn('placeholder="12.345.678-5"', html)
        self.assertIn("data-rut", str(SolicitudActivacionForm()["rut"]))

    def test_servidor_acepta_rut_con_puntos_y_lo_guarda_sin_ellos(self):
        form = SolicitudActivacionForm(data={"rut": "12.345.678-5", "email": "a@example.com"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["rut"], "12345678-5")

    def test_servidor_rechaza_digito_verificador_incorrecto(self):
        form = SolicitudActivacionForm(data={"rut": "12.345.678-6", "email": "a@example.com"})
        self.assertFalse(form.is_valid())
        self.assertIn("rut", form.errors)

    def test_login_funciona_con_el_rut_formateado(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user(rut="12345678-5", password="Ayllu.Demo2026")
        respuesta = self.client.post(reverse("login"), {"username": "12.345.678-5", "password": "Ayllu.Demo2026"})
        self.assertRedirects(respuesta, reverse("panel"), fetch_redirect_response=False)
