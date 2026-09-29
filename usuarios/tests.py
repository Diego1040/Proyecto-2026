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

from .models import (
    AlertaSalud,
    Apoderado,
    ApoderadoJugador,
    Categoria,
    HistorialCategoria,
    Jugador,
    ReglaCategoria,
    SolicitudInscripcion,
    Usuario,
)
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


class PerfilesBloque13Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

        cls.usuario_apoderado = Usuario.objects.create_user(
            rut="20347119-K",
        )
        cls.apoderado = Apoderado.objects.create(
            usuario=cls.usuario_apoderado,
            rut="20347119-K",
            nombres="Ana",
            apellidos="Apoderada",
            telefono="+56911111111",
        )
        cls.jugador_vinculado = Jugador.objects.create(
            rut="11111111-1",
            nombres="Jugador",
            apellidos="Visible",
            fecha_nacimiento=date(2012, 3, 10),
            rama=Jugador.Rama.DAMAS,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        ApoderadoJugador.objects.create(
            apoderado=cls.apoderado,
            jugador=cls.jugador_vinculado,
            parentesco="MADRE",
            es_principal=True,
        )

        cls.jugador_inactivo = Jugador.objects.create(
            rut="33333333-3",
            nombres="Jugador",
            apellidos="Oculto",
            fecha_nacimiento=date(2013, 3, 10),
            rama=Jugador.Rama.VARONES,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        ApoderadoJugador.objects.create(
            apoderado=cls.apoderado,
            jugador=cls.jugador_inactivo,
            parentesco="TUTOR",
            activo=False,
        )

        cls.usuario_jugador = Usuario.objects.create_user(
            rut="12345678-5",
        )
        cls.jugador_con_cuenta = Jugador.objects.create(
            usuario=cls.usuario_jugador,
            rut="12345678-5",
            nombres="Perfil",
            apellidos="Jugador",
            fecha_nacimiento=date(2012, 4, 20),
            rama=Jugador.Rama.DAMAS,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        AlertaSalud.objects.create(
            jugador=cls.jugador_con_cuenta,
            tipo="Alergia",
            descripcion="Alerta visible",
        )
        AlertaSalud.objects.create(
            jugador=cls.jugador_con_cuenta,
            tipo="Antecedente",
            descripcion="Alerta inactiva",
            activa=False,
        )
        categoria = Categoria.objects.get(nombre="U15 Damas")
        HistorialCategoria.objects.create(
            jugador=cls.jugador_con_cuenta,
            categoria_nueva=categoria,
            tipo_cambio=HistorialCategoria.TipoCambio.AUTOMATICO,
        )

    def test_panel_muestra_opciones_segun_perfil(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("panel"))

        self.assertContains(respuesta, reverse("perfil_apoderado"))
        self.assertNotContains(respuesta, reverse("perfil_jugador"))

    def test_perfil_jugador_muestra_solo_alertas_activas_e_historial(self):
        self.client.force_login(self.usuario_jugador)
        respuesta = self.client.get(reverse("perfil_jugador"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Perfil Jugador")
        self.assertContains(respuesta, "Alerta visible")
        self.assertNotContains(respuesta, "Alerta inactiva")
        self.assertContains(respuesta, "U15 Damas")

    def test_perfil_apoderado_muestra_solo_vinculos_activos(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("perfil_apoderado"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Jugador Visible")
        self.assertNotContains(respuesta, "Jugador Oculto")

    def test_perfiles_rechazan_una_cuenta_sin_el_perfil_requerido(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("perfil_jugador"))

        self.assertRedirects(respuesta, reverse("panel"))

    def test_apoderado_agrega_jugador_reutilizando_su_perfil(self):
        self.client.force_login(self.usuario_apoderado)

        respuesta = self.client.post(
            reverse("agregar_jugador_apoderado"),
            {
                "rut": "22222222-2",
                "nombres": "Nuevo",
                "apellidos": "Jugador",
                "fecha_nacimiento": "2014-03-10",
                "rama": Jugador.Rama.VARONES,
                "telefono": "",
                "nombre_contacto_emergencia": "",
                "telefono_contacto_emergencia": "",
                "procedencia": Jugador.Procedencia.INDEPENDIENTE,
                "club_anterior": "",
                "peso_kg": "",
                "talla_cm": "",
                "parentesco": "PADRE",
                "tiene_alerta_salud": "NO",
                "alerta_tipo": "",
                "alerta_descripcion": "",
                "observaciones": "",
                "consentimiento": "on",
            },
        )

        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        self.assertEqual(Apoderado.objects.count(), 1)

        jugador = Jugador.objects.get(rut="22222222-2")
        vinculo = ApoderadoJugador.objects.get(jugador=jugador)
        solicitud = SolicitudInscripcion.objects.get(jugador=jugador)

        self.assertEqual(vinculo.apoderado, self.apoderado)
        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.PENDIENTE,
        )
        self.assertEqual(solicitud.solicitante, self.usuario_apoderado)

    def test_jugador_actualiza_unicamente_su_telefono(self):
        self.client.force_login(self.usuario_jugador)

        respuesta = self.client.post(
            reverse("perfil_jugador"),
            {
                "telefono": "+56987654321",
                "rut": "22222222-2",
                "nombres": "Nombre alterado",
                "apellidos": "Apellido alterado",
                "estado": Jugador.Estado.INACTIVO,
                "procedencia": Jugador.Procedencia.OTRO_CLUB,
            },
        )

        self.assertRedirects(respuesta, reverse("perfil_jugador"))

        jugador = Jugador.objects.get(pk=self.jugador_con_cuenta.pk)
        self.assertEqual(jugador.telefono, "+56987654321")
        self.assertEqual(jugador.rut, "12345678-5")
        self.assertEqual(jugador.nombres, "Perfil")
        self.assertEqual(jugador.apellidos, "Jugador")
        self.assertEqual(jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(
            jugador.procedencia,
            Jugador.Procedencia.INDEPENDIENTE,
        )

    def test_apoderado_actualiza_unicamente_su_telefono(self):
        self.client.force_login(self.usuario_apoderado)

        respuesta = self.client.post(
            reverse("perfil_apoderado"),
            {
                "telefono": "+56912345678",
                "rut": "22222222-2",
                "nombres": "Nombre alterado",
                "apellidos": "Apellido alterado",
            },
        )

        self.assertRedirects(respuesta, reverse("perfil_apoderado"))

        apoderado = Apoderado.objects.get(pk=self.apoderado.pk)
        self.assertEqual(apoderado.telefono, "+56912345678")
        self.assertEqual(apoderado.rut, "20347119-K")
        self.assertEqual(apoderado.nombres, "Ana")
        self.assertEqual(apoderado.apellidos, "Apoderada")

    def test_usuario_no_puede_editar_el_contacto_de_otro_perfil(self):
        telefono_original = Apoderado.objects.get(
            pk=self.apoderado.pk,
        ).telefono
        self.client.force_login(self.usuario_jugador)

        respuesta = self.client.post(
            reverse("perfil_apoderado"),
            {
                "telefono": "+56900000000",
                "apoderado_id": self.apoderado.pk,
            },
        )

        self.assertRedirects(respuesta, reverse("panel"))
        telefono_actual = Apoderado.objects.get(
            pk=self.apoderado.pk,
        ).telefono
        self.assertEqual(telefono_actual, telefono_original)
