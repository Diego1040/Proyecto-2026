"""
Pruebas de las reglas de negocio ya implementadas.

Ejecutar con:
    python manage.py test usuarios
"""
from datetime import date

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Categoria, ReglaCategoria
from .services import calcular_edad, obtener_categoria_automatica
from .validators import normalizar_rut, validar_rut

TEMPORADA = 2026


class ValidadorRutTest(TestCase):
    def test_normaliza_puntos_guiones_y_minusculas(self):
        self.assertEqual(normalizar_rut("12.345.678-5"), "12345678-5")
        self.assertEqual(normalizar_rut("123456785"), "12345678-5")
        self.assertEqual(normalizar_rut("12.345.678-k"), "12345678-K")

    def test_acepta_rut_valido(self):
        validar_rut("12345678-5")

    def test_acepta_digito_verificador_k(self):
        validar_rut("20347119-K")

    def test_rechaza_digito_verificador_incorrecto(self):
        with self.assertRaises(ValidationError):
            validar_rut("12345678-9")

    def test_rechaza_texto_sin_formato_de_rut(self):
        with self.assertRaises(ValidationError):
            validar_rut("no-soy-un-rut")


class CalculoEdadTest(TestCase):
    def test_descuenta_el_anio_si_aun_no_cumple(self):
        edad = calcular_edad(
            date(2012, 12, 31),
            fecha_referencia=date(2026, 6, 1),
        )
        self.assertEqual(edad, 13)

    def test_cuenta_el_anio_el_mismo_dia_del_cumpleanios(self):
        edad = calcular_edad(
            date(2012, 6, 1),
            fecha_referencia=date(2026, 6, 1),
        )
        self.assertEqual(edad, 14)

    def test_rechaza_fecha_futura(self):
        with self.assertRaises(ValidationError):
            calcular_edad(
                date(2030, 1, 1),
                fecha_referencia=date(2026, 6, 1),
            )


class AsignacionCategoriaTest(TestCase):
    """
    Verifica el motor de categorias sobre las categorias reales
    que carga el comando cargar_categorias.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

    def categoria_de(self, fecha_nacimiento, rama):
        return obtener_categoria_automatica(
            fecha_nacimiento=fecha_nacimiento,
            rama=rama,
            temporada=TEMPORADA,
            fecha_referencia=date(2026, 6, 1),
        )

    def test_menor_de_once_cae_en_categoria_mixta(self):
        categoria = self.categoria_de(date(2015, 3, 10), Categoria.Rama.DAMAS)
        self.assertEqual(categoria.nombre, "U11 Mixto")

    def test_jugadora_de_catorce_cae_en_u15_damas(self):
        categoria = self.categoria_de(date(2012, 3, 10), Categoria.Rama.DAMAS)
        self.assertEqual(categoria.nombre, "U15 Damas")

    def test_jugador_de_catorce_cae_en_u15_varones(self):
        categoria = self.categoria_de(date(2012, 3, 10), Categoria.Rama.VARONES)
        self.assertEqual(categoria.nombre, "U15 Varones")

    def test_adulto_cae_en_todo_competidor(self):
        categoria = self.categoria_de(date(1995, 3, 10), Categoria.Rama.VARONES)
        self.assertEqual(categoria.nombre, "T/C Varones")

    def test_sin_regla_aplicable_devuelve_none(self):
        # Cuatro anios: por debajo del tramo minimo cargado.
        self.assertIsNone(
            self.categoria_de(date(2022, 3, 10), Categoria.Rama.VARONES)
        )

    def test_reglas_superpuestas_lanzan_error(self):
        duplicada = Categoria.objects.create(
            nombre="U15 Damas (duplicada)",
            rama=Categoria.Rama.DAMAS,
            orden=99,
        )
        ReglaCategoria.objects.create(
            categoria=duplicada,
            edad_min=14,
            edad_max=15,
            temporada=TEMPORADA,
        )

        with self.assertRaises(ValidationError):
            self.categoria_de(date(2012, 3, 10), Categoria.Rama.DAMAS)

    def test_rama_mixto_no_es_valida_para_un_jugador(self):
        with self.assertRaises(ValidationError):
            self.categoria_de(date(2012, 3, 10), Categoria.Rama.MIXTO)


class PaginasTest(TestCase):
    def test_portada_responde(self):
        respuesta = self.client.get(reverse("inicio"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Ayllu Basket")

    def test_login_responde(self):
        respuesta = self.client.get(reverse("login"))
        self.assertEqual(respuesta.status_code, 200)

    def test_panel_exige_sesion_iniciada(self):
        respuesta = self.client.get(reverse("panel"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)
