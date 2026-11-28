from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .forms import InscripcionJugadorForm
from .models import SolicitudInscripcion
from . import test_inscripcion
from .validators import ERROR_PARENTESCO, PARENTESCOS, normalizar_parentesco, validar_parentesco


class ValidarParentescoTest(SimpleTestCase):
    def test_acepta_las_opciones_de_la_lista(self):
        for opcion in PARENTESCOS:
            with self.subTest(opcion=opcion):
                self.assertEqual(validar_parentesco(opcion), opcion)

    def test_normaliza_mayusculas_y_datos_antiguos(self):
        self.assertEqual(normalizar_parentesco("MADRE"), "Madre")
        self.assertEqual(normalizar_parentesco("tutor"), "Tutor/a legal")
        self.assertEqual(normalizar_parentesco("Abuela"), "Abuelo/a")

    def test_rechaza_texto_libre(self):
        for valor in ("vecino", "asdf", "<script>", "Madre123"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValidationError):
                    validar_parentesco(valor)

    def test_vacio_lo_decide_el_formulario(self):
        self.assertEqual(validar_parentesco(""), "")
        self.assertEqual(validar_parentesco(None), "")


class ParentescoFormularioTest(TestCase):
    datos_adulto = test_inscripcion.InscripcionPublicaSprint2Test.datos_adulto
    datos_menor = test_inscripcion.InscripcionPublicaSprint2Test.datos_menor

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=test_inscripcion.TEMPORADA, verbosity=0)

    def test_el_campo_es_una_lista_desplegable(self):
        respuesta = self.client.get(reverse("inscripcion"))
        self.assertContains(respuesta, '<select name="parentesco"')
        for opcion in PARENTESCOS:
            self.assertContains(respuesta, f'<option value="{opcion}">')

    def test_parentesco_inventado_no_registra_la_inscripcion(self):
        datos = self.datos_menor(rut="24360917-8")
        datos["parentesco"] = "vecino del pasaje"
        respuesta = self.client.post(reverse("inscripcion"), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["form"].errors["parentesco"], [ERROR_PARENTESCO])
        self.assertFalse(SolicitudInscripcion.objects.exists())

    def test_parentesco_valido_se_guarda_tal_cual_la_lista(self):
        datos = self.datos_menor(rut="24360917-8")
        datos["parentesco"] = "Abuelo/a"
        form = InscripcionJugadorForm(datos)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["parentesco"], "Abuelo/a")
