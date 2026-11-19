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
from .services import calcular_edad, calcular_edad_deportiva, obtener_categoria_automatica
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
        self.assertEqual(categoria.nombre, "Todo Competidor Varones")

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

    # NUEVO AGREGADO

    def test_edad_deportiva_es_por_anio_de_nacimiento(self):
        self.assertEqual(calcular_edad_deportiva(date(2012, 1, 1), 2026), 14)
        self.assertEqual(calcular_edad_deportiva(date(2012, 12, 31), 2026), 14)

    def test_nacido_en_diciembre_queda_con_los_de_su_anio(self):
        categoria = self.categoria_de(date(2012, 12, 20), Categoria.Rama.VARONES)
        self.assertEqual(categoria.nombre, "U15 Varones")

    def test_misma_categoria_todo_el_anio_de_nacimiento(self):
        enero = self.categoria_de(date(2013, 1, 5), Categoria.Rama.DAMAS)
        diciembre = self.categoria_de(date(2013, 12, 20), Categoria.Rama.DAMAS)
        self.assertEqual(enero, diciembre)
        self.assertEqual(enero.nombre, "U13 Damas")

    def test_fecha_nacimiento_futura_lanza_error(self):
        with self.assertRaises(ValidationError):
            self.categoria_de(date(2026, 12, 1), Categoria.Rama.DAMAS)

    # >>> NUEVO (HU-05) - Miguel: las 11 categorias -------------------
    def test_existen_11_categorias_activas(self):
        self.assertEqual(Categoria.objects.filter(activa=True).count(), 11)

    def test_seis_y_siete_anios_caen_en_u7_mixto(self):
        # 2026 - 2020 = 6 y 2026 - 2019 = 7
        self.assertEqual(self.categoria_de(date(2020, 5, 1), Categoria.Rama.DAMAS).nombre, "U7 Mixto")
        self.assertEqual(self.categoria_de(date(2019, 5, 1), Categoria.Rama.VARONES).nombre, "U7 Mixto")

    def test_ocho_y_nueve_anios_caen_en_u9_mixto(self):
        # 2026 - 2018 = 8 y 2026 - 2017 = 9
        self.assertEqual(self.categoria_de(date(2018, 5, 1), Categoria.Rama.DAMAS).nombre, "U9 Mixto")
        self.assertEqual(self.categoria_de(date(2017, 5, 1), Categoria.Rama.VARONES).nombre, "U9 Mixto")

    def test_recargar_desactiva_mini_mixto_antigua(self):
        # Simula una base de datos que todavia tiene la categoria antigua
        mini = Categoria.objects.create(
            nombre="Mini Mixto", rama=Categoria.Rama.MIXTO, orden=99,
        )
        ReglaCategoria.objects.create(
            categoria=mini, edad_min=6, edad_max=9, temporada=TEMPORADA,
        )

        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

        mini.refresh_from_db()
        self.assertFalse(mini.activa)
        # Sin superposicion: sigue funcionando el calculo
        self.assertEqual(self.categoria_de(date(2018, 5, 1), Categoria.Rama.DAMAS).nombre, "U9 Mixto")
    # <<< FIN NUEVO (HU-05) --------------------------------------------

    # FIN NUEVO AGREGADO


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


# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# NUEVO (HU-05) - Miguel: pruebas de la excepcion manual
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import Apoderado, HistorialCategoria, Jugador
from .services import asignar_categoria_automatica


class ExcepcionCategoriaTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", verbosity=0)
        Usuario = get_user_model()

        grupo, _ = Group.objects.get_or_create(name="Administración")
        cls.secretaria = Usuario.objects.create_user(
            rut="22222222-2", password="clave-segura-123",
        )
        cls.secretaria.groups.add(grupo)

        cls.apoderado = Usuario.objects.create_user(
            rut="11111111-1", password="clave-segura-123",
        )
        Apoderado.objects.create(
            usuario=cls.apoderado, rut="11111111-1",
            nombres="Carolina", apellidos="Vergara", telefono="1",
        )

    def setUp(self):
        self.jugador = Jugador.objects.create(
            rut="23456789-6", nombres="Miguel", apellidos="Cortes",
            fecha_nacimiento=date(2012, 3, 15),
            rama=Categoria.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO,
        )
        asignar_categoria_automatica(self.jugador)
        self.u17 = Categoria.objects.get(nombre="U17 Varones")
        self.url = reverse("categorias_jugadores")

    def test_administracion_ve_la_pantalla(self):
        self.client.force_login(self.secretaria)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Miguel")

    def test_apoderado_no_puede_entrar(self):
        self.client.force_login(self.apoderado)
        respuesta = self.client.get(self.url)
        self.assertRedirects(respuesta, reverse("panel"), fetch_redirect_response=False)

    def test_excepcion_exige_motivo(self):
        self.client.force_login(self.secretaria)
        self.client.post(self.url, {
            "jugador_id": self.jugador.pk,
            "categoria_id": self.u17.pk,
            "motivo": "   ",
        })
        self.jugador.refresh_from_db()
        self.assertEqual(self.jugador.categoria_actual.nombre, "U15 Varones")

    def test_excepcion_con_motivo_cambia_y_deja_historial(self):
        self.client.force_login(self.secretaria)
        self.client.post(self.url, {
            "jugador_id": self.jugador.pk,
            "categoria_id": self.u17.pk,
            "motivo": "Autorizado por el entrenador",
        })
        self.jugador.refresh_from_db()
        self.assertEqual(self.jugador.categoria_actual, self.u17)

        ultimo = self.jugador.historial_categorias.order_by("-fecha").first()
        self.assertEqual(ultimo.tipo_cambio, HistorialCategoria.TipoCambio.EXCEPCION_MANUAL)
        self.assertEqual(ultimo.cambiado_por, self.secretaria)

    def test_recalcular_no_pisa_la_excepcion_manual(self):
        self.client.force_login(self.secretaria)
        self.client.post(self.url, {
            "jugador_id": self.jugador.pk,
            "categoria_id": self.u17.pk,
            "motivo": "Autorizado por el entrenador",
        })
        self.jugador.refresh_from_db()

        asignar_categoria_automatica(self.jugador)

        self.jugador.refresh_from_db()
        self.assertEqual(self.jugador.categoria_actual, self.u17)
# FIN NUEVO (HU-05)