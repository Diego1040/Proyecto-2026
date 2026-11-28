from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .forms import ContactoApoderadoForm
from .forms_mi_cuenta import MiCuentaForm
from .models import SolicitudInscripcion
from . import test_inscripcion
from .validators import ERROR_TELEFONO, validar_telefono


class ValidarTelefonoTest(SimpleTestCase):
    def test_acepta_formatos_chilenos_y_los_deja_como_56_9(self):
        for valor in ("+56987654321", "+56 9 8765 4321", "56987654321", "987654321", "9 8765-4321", "(+56) 9.8765.4321"):
            with self.subTest(valor=valor):
                self.assertEqual(validar_telefono(f"  {valor} "), "+56 9 8765 4321")

    def test_rechaza_lo_que_no_es_celular(self):
        # fijo de Arica, fijo sin 9 y números que no comienzan con 9
        for valor in ("+56 58 223 4567", "582234567", "812345678", "+56 2 2345 6789"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValidationError):
                    validar_telefono(valor)

    def test_vacio_se_acepta_y_la_obligatoriedad_la_decide_el_formulario(self):
        self.assertEqual(validar_telefono(""), "")
        self.assertEqual(validar_telefono(None), "")

    def test_rechaza_telefonos_incompletos_o_con_letras(self):
        for valor in ("123", "+5694402090", "98765432", "+56 9 8765 43210", "abc987654321", "+1 555 123 4567"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValidationError):
                    validar_telefono(valor)


class FormulariosTelefonoTest(SimpleTestCase):
    def test_contacto_del_apoderado_rechaza_telefono_invalido(self):
        form = ContactoApoderadoForm(data={"telefono": "123", "email": "apoderado@example.com"})
        self.assertFalse(form.is_valid())
        self.assertIn("telefono", form.errors)

    def test_contacto_del_apoderado_acepta_telefono_valido(self):
        form = ContactoApoderadoForm(data={"telefono": "+56 9 8765 4321", "email": "apoderado@example.com"})
        self.assertNotIn("telefono", form.errors)

    def test_mis_datos_personales_rechaza_telefono_invalido(self):
        form = MiCuentaForm(data={"first_name": "Ana", "last_name": "Rojas", "email": "ana@example.com", "telefono": "123"})
        self.assertFalse(form.is_valid())
        self.assertIn("telefono", form.errors)


class InscripcionTelefonoTest(TestCase):
    datos_adulto = test_inscripcion.InscripcionPublicaSprint2Test.datos_adulto
    datos_menor = test_inscripcion.InscripcionPublicaSprint2Test.datos_menor

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=test_inscripcion.TEMPORADA, verbosity=0)

    def test_telefono_del_apoderado_invalido_muestra_un_solo_error_y_no_registra(self):
        datos = self.datos_menor(rut="24360917-8")
        datos["telefono_apoderado"] = "+5694402090"
        respuesta = self.client.post(reverse("inscripcion"), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.context["form"].errors["telefono_apoderado"],
            [ERROR_TELEFONO],
        )
        self.assertFalse(SolicitudInscripcion.objects.exists())


class TelefonoFrontendTest(SimpleTestCase):
    def test_campo_muestra_ejemplo_y_patron_en_el_navegador(self):
        html = str(ContactoApoderadoForm()["telefono"])
        self.assertIn('placeholder="+56 9 1234 5678"', html)
        self.assertIn("pattern=", html)
        self.assertIn('inputmode="tel"', html)


class TelefonoSeGuardaNormalizadoTest(SimpleTestCase):
    def test_formulario_devuelve_el_formato_estandar(self):
        form = ContactoApoderadoForm(data={"telefono": "987654321", "email": "apoderado@example.com"})
        form.is_valid()
        self.assertEqual(form.cleaned_data.get("telefono"), "+56 9 8765 4321")
