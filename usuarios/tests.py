"""
Pruebas de las reglas de negocio ya implementadas.

Ejecutar con:
    python manage.py test usuarios
"""
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import InscripcionJugadorForm
from .models import (
    AlertaSalud,
    Apoderado,
    ApoderadoJugador,
    Auditoria,
    Categoria,
    HistorialCategoria,
    Jugador,
    ReglaCategoria,
    SolicitudInscripcion,
    Usuario,
)
from .services import (
    calcular_edad,
    marcar_solicitud_en_revision,
    obtener_categoria_automatica,
    rechazar_solicitud_inscripcion,
)
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
            email="ana@example.com",
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
            fecha_nacimiento=date(1990, 4, 20),
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
        categoria = Categoria.objects.get(nombre="T/C Damas")
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
        self.assertContains(respuesta, "T/C Damas")

    def test_perfil_apoderado_muestra_solo_vinculos_activos(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("perfil_apoderado"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Jugador Visible")
        self.assertNotContains(respuesta, "Jugador Oculto")
        self.assertNotContains(respuesta, "Permiso de gestión")
        self.assertNotContains(respuesta, "Habilitado")
        self.assertNotContains(respuesta, "Solo consulta")
        self.assertTrue(self.apoderado.vinculos_jugadores.get(activo=True).puede_gestionar)

    def test_perfil_apoderado_muestra_solo_consulta_sin_cambiar_permiso(self):
        vinculo = self.apoderado.vinculos_jugadores.get(activo=True)
        vinculo.puede_gestionar = False
        vinculo.save(update_fields=["puede_gestionar"])
        self.client.force_login(self.usuario_apoderado)

        respuesta = self.client.get(reverse("perfil_apoderado"))

        self.assertContains(respuesta, "Solo consulta")
        self.assertNotContains(respuesta, "Permiso de gestión")
        vinculo.refresh_from_db()
        self.assertFalse(vinculo.puede_gestionar)

    def test_parentesco_inicial_considera_todos_y_solo_los_vinculos_activos(self):
        self.client.force_login(self.usuario_apoderado)
        casos = (
            (True, False, "TUTOR", "MADRE"),
            (True, True, "MADRE", "MADRE"),
            (True, True, "TUTOR", ""),
            (False, False, "TUTOR", ""),
        )
        for primero_activo, segundo_activo, segundo_parentesco, esperado in casos:
            with self.subTest(caso=(primero_activo, segundo_activo, segundo_parentesco)):
                self.apoderado.vinculos_jugadores.filter(jugador=self.jugador_vinculado).update(
                    activo=primero_activo,
                )
                self.apoderado.vinculos_jugadores.filter(jugador=self.jugador_inactivo).update(
                    activo=segundo_activo, parentesco=segundo_parentesco,
                )
                respuesta = self.client.get(reverse("agregar_jugador_apoderado"))
                form = respuesta.context["form"]
                self.assertEqual(form["parentesco"].value(), esperado)
                self.assertFalse(form.fields["parentesco"].disabled)
                self.assertNotIn("rut_apoderado", form.fields)
                self.assertNotIn("email_apoderado", form.fields)

    def test_post_invalido_conserva_parentesco_elegido_y_no_asume_uno_omitido(self):
        self.client.force_login(self.usuario_apoderado)
        for datos, esperado in (({"parentesco": "TUTOR"}, "TUTOR"), ({}, None)):
            with self.subTest(datos=datos):
                respuesta = self.client.post(reverse("agregar_jugador_apoderado"), datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.context["form"]["parentesco"].value(), esperado)

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
                "email": "",
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
        self.assertEqual(vinculo.parentesco, "PADRE")
        self.apoderado.refresh_from_db()
        self.assertEqual(self.apoderado.email, "ana@example.com")
        self.assertEqual(self.apoderado.telefono, "+56911111111")
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


class FormularioInscripcionSprint2Test(TestCase):
    def datos_validos(self, **cambios):
        datos = {
            "rut": "22222222-2",
            "nombres": "Camila",
            "apellidos": "Deportista",
            "fecha_nacimiento": "1990-05-10",
            "rama": Jugador.Rama.DAMAS,
            "telefono": "+56912345678",
            "email": "camila@example.com",
            "nombre_contacto_emergencia": "Contacto Adulto",
            "telefono_contacto_emergencia": "+56987654321",
            "procedencia": Jugador.Procedencia.INDEPENDIENTE,
            "club_anterior": "",
            "peso_kg": "65.5",
            "talla_cm": "170",
            "rut_apoderado": "",
            "nombres_apoderado": "",
            "apellidos_apoderado": "",
            "telefono_apoderado": "",
            "email_apoderado": "",
            "parentesco": "",
            "tiene_alerta_salud": "NO",
            "alerta_tipo": "",
            "alerta_descripcion": "",
            "observaciones": "",
            "consentimiento": "on",
        }
        datos.update(cambios)
        return datos

    def test_validaciones_diferencian_menor_y_adulto(self):
        formulario_menor = InscripcionJugadorForm(
            self.datos_validos(
                fecha_nacimiento="2012-05-10",
                telefono="",
                email="",
                nombre_contacto_emergencia="",
                telefono_contacto_emergencia="",
            ),
        )

        self.assertFalse(formulario_menor.is_valid())
        self.assertIn("rut_apoderado", formulario_menor.errors)
        self.assertIn("nombres_apoderado", formulario_menor.errors)
        self.assertIn("apellidos_apoderado", formulario_menor.errors)
        self.assertIn("telefono_apoderado", formulario_menor.errors)
        self.assertIn("parentesco", formulario_menor.errors)
        self.assertNotIn("telefono", formulario_menor.errors)

        formulario_adulto = InscripcionJugadorForm(
            self.datos_validos(
                telefono="",
                nombre_contacto_emergencia="",
                telefono_contacto_emergencia="",
            ),
        )

        self.assertFalse(formulario_adulto.is_valid())
        self.assertIn("telefono", formulario_adulto.errors)
        self.assertIn(
            "nombre_contacto_emergencia",
            formulario_adulto.errors,
        )
        self.assertIn(
            "telefono_contacto_emergencia",
            formulario_adulto.errors,
        )
        self.assertNotIn("rut_apoderado", formulario_adulto.errors)
        self.assertNotIn("parentesco", formulario_adulto.errors)

    def test_otro_club_es_obligatorio_e_independiente_lo_limpia(self):
        formulario_otro_club = InscripcionJugadorForm(
            self.datos_validos(
                procedencia=Jugador.Procedencia.OTRO_CLUB,
                club_anterior="",
            ),
        )

        self.assertFalse(formulario_otro_club.is_valid())
        self.assertIn("club_anterior", formulario_otro_club.errors)

        formulario_independiente = InscripcionJugadorForm(
            self.datos_validos(
                procedencia=Jugador.Procedencia.INDEPENDIENTE,
                club_anterior="Club que debe ignorarse",
            ),
        )

        self.assertTrue(formulario_independiente.is_valid())
        self.assertEqual(
            formulario_independiente.cleaned_data["club_anterior"],
            "",
        )

    def test_alerta_si_exige_detalle_y_alerta_no_lo_limpia(self):
        formulario_con_alerta_incompleta = InscripcionJugadorForm(
            self.datos_validos(
                tiene_alerta_salud="SI",
                alerta_tipo="",
                alerta_descripcion="",
            ),
        )

        self.assertFalse(formulario_con_alerta_incompleta.is_valid())
        self.assertIn("alerta_tipo", formulario_con_alerta_incompleta.errors)
        self.assertIn(
            "alerta_descripcion",
            formulario_con_alerta_incompleta.errors,
        )

        formulario_sin_alerta = InscripcionJugadorForm(
            self.datos_validos(
                tiene_alerta_salud="NO",
                alerta_tipo="Dato que debe ignorarse",
                alerta_descripcion="Descripción que debe ignorarse",
            ),
        )

        self.assertTrue(formulario_sin_alerta.is_valid())
        self.assertEqual(formulario_sin_alerta.cleaned_data["alerta_tipo"], "")
        self.assertEqual(
            formulario_sin_alerta.cleaned_data["alerta_descripcion"],
            "",
        )


class InscripcionPublicaSprint2Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

    def datos_adulto(self, **cambios):
        datos = {
            "rut": "11111111-1",
            "nombres": "Alex",
            "apellidos": "Adulto",
            "fecha_nacimiento": "1990-03-10",
            "rama": Jugador.Rama.VARONES,
            "telefono": "+56911112222",
            "email": "alex@example.com",
            "nombre_contacto_emergencia": "Contacto Emergencia",
            "telefono_contacto_emergencia": "+56933334444",
            "procedencia": Jugador.Procedencia.INDEPENDIENTE,
            "club_anterior": "",
            "peso_kg": "80",
            "talla_cm": "182",
            "tiene_alerta_salud": "NO",
            "alerta_tipo": "",
            "alerta_descripcion": "",
            "observaciones": "Inscripción de adulto",
            "consentimiento": "on",
        }
        datos.update(cambios)
        return datos

    def test_inscripcion_publica_adulto_no_crea_apoderado(self):
        respuesta = self.client.post(
            reverse("inscripcion"),
            self.datos_adulto(),
        )

        self.assertRedirects(respuesta, reverse("inscripcion_exito"))

        jugador = Jugador.objects.get(rut="11111111-1")
        solicitud = SolicitudInscripcion.objects.get(jugador=jugador)

        self.assertEqual(jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(jugador.categoria_actual.nombre, "T/C Varones")
        self.assertEqual(jugador.procedencia, Jugador.Procedencia.INDEPENDIENTE)
        self.assertEqual(jugador.club_anterior, "")
        self.assertEqual(jugador.vinculos_apoderados.count(), 0)
        self.assertEqual(Apoderado.objects.count(), 0)
        self.assertEqual(AlertaSalud.objects.count(), 0)
        self.assertEqual(Usuario.objects.count(), 0)
        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.PENDIENTE,
        )
        self.assertIsNone(solicitud.solicitante)
        self.assertTrue(solicitud.consentimiento)

    def test_inscripcion_publica_menor_crea_apoderado_vinculo_y_alerta(self):
        datos = self.datos_adulto(
            rut="22222222-2",
            nombres="Martina",
            apellidos="Menor",
            fecha_nacimiento="2012-03-10",
            rama=Jugador.Rama.DAMAS,
            telefono="",
            email="",
            nombre_contacto_emergencia="",
            telefono_contacto_emergencia="",
            procedencia=Jugador.Procedencia.OTRO_CLUB,
            club_anterior="Club de origen",
            rut_apoderado="20347119-K",
            nombres_apoderado="Andrea",
            apellidos_apoderado="Responsable",
            telefono_apoderado="+56955556666",
            email_apoderado="andrea@example.com",
            parentesco="MADRE",
            tiene_alerta_salud="SI",
            alerta_tipo="Alergia",
            alerta_descripcion="Reacción a frutos secos",
        )

        respuesta = self.client.post(reverse("inscripcion"), datos)

        self.assertRedirects(respuesta, reverse("inscripcion_exito"))

        jugador = Jugador.objects.get(rut="22222222-2")
        apoderado = Apoderado.objects.get(rut="20347119-K")
        vinculo = ApoderadoJugador.objects.get(
            jugador=jugador,
            apoderado=apoderado,
        )
        alerta = AlertaSalud.objects.get(jugador=jugador)
        solicitud = SolicitudInscripcion.objects.get(jugador=jugador)

        self.assertEqual(jugador.categoria_actual.nombre, "U15 Damas")
        self.assertEqual(jugador.club_anterior, "Club de origen")
        self.assertTrue(vinculo.activo)
        self.assertTrue(vinculo.es_principal)
        self.assertEqual(vinculo.parentesco, "MADRE")
        self.assertIsNone(apoderado.usuario)
        self.assertEqual(alerta.tipo, "Alergia")
        self.assertTrue(alerta.activa)
        self.assertEqual(solicitud.club_anterior, "Club de origen")
        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.PENDIENTE,
        )


@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
class GestionSolicitudesSprint2Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

        cls.staff = Usuario.objects.create_user(
            rut="20347119-K",
            is_staff=True,
        )
        cls.usuario_sin_permiso = Usuario.objects.create_user(
            rut="11111111-1",
        )
        categoria = Categoria.objects.get(nombre="U15 Varones")
        cls.jugador = Jugador.objects.create(
            rut="22222222-2",
            nombres="Jugador",
            apellidos="En revisión",
            fecha_nacimiento=date(2012, 3, 10),
            rama=Jugador.Rama.VARONES,
            categoria_actual=categoria,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        cls.apoderado = Apoderado.objects.create(
            rut="12345678-5",
            nombres="Patricia",
            apellidos="Responsable",
            telefono="+56955556666",
            email="patricia@example.com",
        )
        ApoderadoJugador.objects.create(
            apoderado=cls.apoderado,
            jugador=cls.jugador,
            parentesco="MADRE",
            es_principal=True,
            puede_gestionar=True,
        )
        cls.solicitud = SolicitudInscripcion.objects.create(
            jugador=cls.jugador,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
            consentimiento=True,
        )

    def test_staff_accede_a_listado_y_detalle_sin_grupo_adicional(self):
        self.assertFalse(self.staff.groups.exists())
        self.client.force_login(self.staff)

        listado = self.client.get(reverse("solicitudes_administracion"))
        detalle = self.client.get(
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )

        self.assertEqual(listado.status_code, 200)
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(listado, "Jugador En revisión")
        self.assertContains(detalle, "Solicitud #")

    def test_usuario_no_staff_no_accede_ni_cambia_estado(self):
        self.client.force_login(self.usuario_sin_permiso)

        listado = self.client.get(reverse("solicitudes_administracion"))
        detalle = self.client.get(
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )
        revision = self.client.post(
            reverse("solicitud_iniciar_revision", args=[self.solicitud.pk]),
        )

        self.assertEqual(listado.status_code, 302)
        self.assertIn(reverse("login"), listado.url)
        self.assertEqual(detalle.status_code, 302)
        self.assertIn(reverse("login"), detalle.url)
        self.assertEqual(revision.status_code, 302)

        solicitud = SolicitudInscripcion.objects.get(pk=self.solicitud.pk)
        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.PENDIENTE,
        )

    def test_revision_y_aprobacion_activan_al_jugador(self):
        self.client.force_login(self.staff)

        respuesta_revision = self.client.post(
            reverse("solicitud_iniciar_revision", args=[self.solicitud.pk]),
        )
        self.assertRedirects(
            respuesta_revision,
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )

        solicitud = SolicitudInscripcion.objects.get(pk=self.solicitud.pk)
        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.EN_REVISION,
        )

        respuesta_aprobacion = self.client.post(
            reverse("solicitud_aprobar", args=[self.solicitud.pk]),
        )
        self.assertRedirects(
            respuesta_aprobacion,
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )

        solicitud.refresh_from_db()
        jugador = Jugador.objects.get(pk=self.jugador.pk)

        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.APROBADA,
        )
        self.assertEqual(solicitud.revisado_por, self.staff)
        self.assertIsNotNone(solicitud.fecha_revision)
        self.assertEqual(jugador.estado, Jugador.Estado.ACTIVO)
        self.assertIsNotNone(jugador.fecha_ingreso)
        self.assertTrue(
            Auditoria.objects.filter(
                accion="SOLICITUD_APROBADA",
                entidad_id=solicitud.pk,
                usuario=self.staff,
            ).exists(),
        )

    def test_rechazo_exige_motivo_y_registra_el_valido(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("solicitud_iniciar_revision", args=[self.solicitud.pk]),
        )

        respuesta_sin_motivo = self.client.post(
            reverse("solicitud_rechazar", args=[self.solicitud.pk]),
            {"motivo": "   "},
        )
        self.assertRedirects(
            respuesta_sin_motivo,
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )

        solicitud = SolicitudInscripcion.objects.get(pk=self.solicitud.pk)
        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.EN_REVISION,
        )
        self.assertEqual(solicitud.motivo_rechazo, "")

        respuesta_con_motivo = self.client.post(
            reverse("solicitud_rechazar", args=[self.solicitud.pk]),
            {"motivo": "Antecedentes incompletos"},
        )
        self.assertRedirects(
            respuesta_con_motivo,
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )

        solicitud.refresh_from_db()
        jugador = Jugador.objects.get(pk=self.jugador.pk)

        self.assertEqual(
            solicitud.estado,
            SolicitudInscripcion.Estado.RECHAZADA,
        )
        self.assertEqual(
            solicitud.motivo_rechazo,
            "Antecedentes incompletos",
        )
        self.assertEqual(solicitud.revisado_por, self.staff)
        self.assertIsNotNone(solicitud.fecha_revision)
        self.assertEqual(jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertIsNone(jugador.usuario_id)
        self.assertIsNone(solicitud.usuario_autorizado_id)
        self.apoderado.refresh_from_db()
        self.assertIsNone(self.apoderado.usuario_id)
        self.assertEqual(Usuario.objects.count(), 2)
        self.assertEqual(Jugador.objects.count(), 1)
        self.assertEqual(SolicitudInscripcion.objects.count(), 1)
        self.assertTrue(
            Auditoria.objects.filter(
                accion="SOLICITUD_RECHAZADA",
                entidad_id=solicitud.pk,
                usuario=self.staff,
            ).exists(),
        )

    def test_lista_muestra_accion_por_estado_y_get_no_lo_cambia(self):
        self.client.force_login(self.staff)
        casos = (
            (SolicitudInscripcion.Estado.PENDIENTE, "Tomar en revisión"),
            (SolicitudInscripcion.Estado.EN_REVISION, "Continuar revisión"),
            (SolicitudInscripcion.Estado.APROBADA, "Ver detalle"),
            (SolicitudInscripcion.Estado.RECHAZADA, "Ver detalle"),
        )
        for estado, etiqueta in casos:
            with self.subTest(estado=estado):
                SolicitudInscripcion.objects.filter(pk=self.solicitud.pk).update(estado=estado)
                listado = self.client.get(reverse("solicitudes_administracion"))
                self.assertContains(listado, etiqueta)
                if estado == SolicitudInscripcion.Estado.PENDIENTE:
                    self.assertContains(
                        listado,
                        f'<form method="post" action="{reverse("solicitud_iniciar_revision", args=[self.solicitud.pk])}">',
                    )
                    self.assertContains(listado, 'name="csrfmiddlewaretoken"')
                else:
                    self.assertNotContains(listado, "Tomar en revisión")
                    self.assertContains(listado, reverse("solicitud_detalle", args=[self.solicitud.pk]))
                detalle = self.client.get(reverse("solicitud_detalle", args=[self.solicitud.pk]))
                self.assertEqual(detalle.status_code, 200)
                self.solicitud.refresh_from_db()
                self.assertEqual(self.solicitud.estado, estado)

    def test_get_de_acciones_no_cambia_estado(self):
        self.client.force_login(self.staff)
        for accion in ("solicitud_iniciar_revision", "solicitud_aprobar", "solicitud_rechazar"):
            with self.subTest(accion=accion):
                respuesta = self.client.get(reverse(accion, args=[self.solicitud.pk]))
                self.assertEqual(respuesta.status_code, 405)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_tomar_revision_exige_csrf_y_abre_detalle(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.staff)
        cliente.get(reverse("solicitudes_administracion"))
        ruta = reverse("solicitud_iniciar_revision", args=[self.solicitud.pk])
        self.assertEqual(cliente.post(ruta).status_code, 403)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)

        respuesta = cliente.post(ruta, {"csrfmiddlewaretoken": cliente.cookies["csrftoken"].value})

        self.assertRedirects(respuesta, reverse("solicitud_detalle", args=[self.solicitud.pk]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

    def test_rechazo_envia_correo_al_principal_despues_del_commit_sin_datos_sensibles(self):
        self.jugador.email = "menor@example.com"
        self.jugador.peso_kg = 55
        self.jugador.talla_cm = 170
        self.jugador.save(update_fields=["email", "peso_kg", "talla_cm"])
        self.solicitud.observaciones = "Antecedente privado de la solicitud"
        self.solicitud.save(update_fields=["observaciones"])
        AlertaSalud.objects.create(
            jugador=self.jugador, tipo="Alergia privada", descripcion="Diagnóstico reservado",
        )
        secundario = Apoderado.objects.create(
            rut="33333333-3", nombres="Otro", apellidos="Apoderado", email="otro@example.com",
        )
        ApoderadoJugador.objects.create(
            apoderado=secundario, jugador=self.jugador, parentesco="TUTOR",
        )
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        self.client.force_login(self.staff)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            respuesta = self.client.post(
                reverse("solicitud_rechazar", args=[self.solicitud.pk]),
                {"motivo": "  Antecedentes incompletos & pendientes  "},
            )
            self.assertEqual(respuesta.status_code, 302)
            self.assertEqual(len(mail.outbox), 0)

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["patricia@example.com"])
        self.assertIn("Antecedentes incompletos & pendientes", correo.body)
        self.assertIn("contacta a la administración del club", correo.body)
        texto = correo.subject + correo.body
        for privado in (
            "Alergia privada", "Diagnóstico reservado", "Antecedente privado de la solicitud",
            self.jugador.rut, self.apoderado.rut, self.apoderado.telefono,
            "peso", "talla", "menor@example.com", "/activar-cuenta/",
        ):
            self.assertNotIn(privado, texto)
        self.assertEqual(AlertaSalud.objects.filter(jugador=self.jugador).count(), 1)

    def test_rechazo_adulto_envia_a_jugador_y_no_al_apoderado(self):
        self.jugador.fecha_nacimiento = date(1990, 3, 10)
        self.jugador.email = "adulto@example.com"
        self.jugador.save(update_fields=["fecha_nacimiento", "email"])
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            rechazar_solicitud_inscripcion(
                solicitud=self.solicitud, usuario=self.staff, motivo="Antecedentes incompletos",
            )
            self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(mail.outbox[0].to, ["adulto@example.com"])
        self.jugador.refresh_from_db()
        self.solicitud.refresh_from_db()
        self.assertEqual(self.jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertIsNone(self.jugador.usuario_id)
        self.assertIsNone(self.solicitud.usuario_autorizado_id)
        self.assertEqual(Usuario.objects.count(), 2)

    def test_rechazo_no_modifica_cuenta_existente_del_apoderado(self):
        self.apoderado.usuario = self.staff
        self.apoderado.rut = self.staff.rut
        self.apoderado.save(update_fields=["usuario", "rut"])
        credenciales = (self.staff.password, self.staff.is_active, self.staff.email)
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        with self.captureOnCommitCallbacks(execute=True):
            rechazar_solicitud_inscripcion(
                solicitud=self.solicitud, usuario=self.staff, motivo="Antecedentes incompletos",
            )
        self.staff.refresh_from_db()
        self.apoderado.refresh_from_db()
        self.solicitud.refresh_from_db()
        self.assertEqual(credenciales, (self.staff.password, self.staff.is_active, self.staff.email))
        self.assertEqual(self.apoderado.usuario_id, self.staff.pk)
        self.assertIsNone(self.solicitud.usuario_autorizado_id)
        self.assertEqual(Usuario.objects.count(), 2)

    def test_rechazo_exige_personal_administrativo_en_servicio(self):
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        for usuario in (None, AnonymousUser(), self.usuario_sin_permiso):
            with self.subTest(usuario=usuario):
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    with self.assertRaises(ValidationError):
                        rechazar_solicitud_inscripcion(
                            solicitud=self.solicitud, usuario=usuario, motivo="Antecedentes incompletos",
                        )
                self.assertEqual(callbacks, [])
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_rechazo_invalido_no_registra_resolucion_ni_correo(self):
        casos = (
            (SolicitudInscripcion.Estado.PENDIENTE, "Motivo"),
            (SolicitudInscripcion.Estado.APROBADA, "Motivo"),
            (SolicitudInscripcion.Estado.EN_REVISION, "   "),
        )
        for estado, motivo in casos:
            with self.subTest(estado=estado, motivo=motivo):
                SolicitudInscripcion.objects.filter(pk=self.solicitud.pk).update(estado=estado)
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    with self.assertRaises(ValidationError):
                        rechazar_solicitud_inscripcion(
                            solicitud=self.solicitud, usuario=self.staff, motivo=motivo,
                        )
                self.solicitud.refresh_from_db()
                self.assertEqual(self.solicitud.estado, estado)
                self.assertIsNone(self.solicitud.fecha_revision)
                self.assertEqual(callbacks, [])
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_rechazo_repetido_recarga_estado_y_no_duplica_correo_ni_auditoria(self):
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        instancia_desactualizada = SolicitudInscripcion.objects.get(pk=self.solicitud.pk)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            resolucion = rechazar_solicitud_inscripcion(
                solicitud=self.solicitud, usuario=self.staff, motivo="Primer motivo",
            )
            with self.assertRaises(ValidationError):
                rechazar_solicitud_inscripcion(
                    solicitud=instancia_desactualizada, usuario=self.staff, motivo="Segundo motivo",
                )
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.motivo_rechazo, "Primer motivo")
        self.assertEqual(self.solicitud.fecha_revision, resolucion.fecha_revision)
        self.assertEqual(self.solicitud.revisado_por_id, self.staff.pk)
        self.assertEqual(Auditoria.objects.filter(accion="SOLICITUD_RECHAZADA").count(), 1)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_rollback_externo_descarta_rechazo_auditoria_y_correo(self):
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(ValidationError):
                with transaction.atomic():
                    rechazar_solicitud_inscripcion(
                        solicitud=self.solicitud, usuario=self.staff, motivo="Antecedentes incompletos",
                    )
                    raise ValidationError("Cancelar transacción externa")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(self.solicitud.motivo_rechazo, "")
        self.assertIsNone(self.solicitud.revisado_por_id)
        self.assertIsNone(self.solicitud.fecha_revision)
        self.assertIsNone(self.solicitud.usuario_autorizado_id)
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_error_en_auditoria_revierte_rechazo_sin_correo(self):
        marcar_solicitud_en_revision(solicitud=self.solicitud)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Error de auditoría")):
                with self.assertRaises(ValidationError):
                    rechazar_solicitud_inscripcion(
                        solicitud=self.solicitud, usuario=self.staff, motivo="Antecedentes incompletos",
                    )
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(self.solicitud.motivo_rechazo, "")
        self.assertIsNone(self.solicitud.fecha_revision)
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)
