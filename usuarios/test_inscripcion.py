"""Inscripción y revisión integradas sobre la base de Miguel."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import InscripcionJugadorForm
from .models import (AlertaSalud, Apoderado, ApoderadoJugador, Auditoria,
                     Categoria, Jugador, SolicitudInscripcion, Usuario)
from .services import (aprobar_solicitud_inscripcion, crear_solicitud_inscripcion,
                       inscribir_jugador, marcar_solicitud_en_revision,
                       rechazar_solicitud_inscripcion)
from .validators import ERROR_IDENTIDAD_INSCRIPCION

TEMPORADA = 2026

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

    def test_get_publico_redirige_usuario_autenticado_con_o_sin_perfil_apoderado(self):
        usuario = Usuario.objects.create_user(rut="20347119-K")
        self.client.force_login(usuario)
        for es_apoderado in (False, True):
            with self.subTest(es_apoderado=es_apoderado):
                if es_apoderado:
                    Apoderado.objects.create(
                        usuario=usuario, rut=usuario.rut, nombres="Cuenta", apellidos="Existente",
                        telefono="+56911111111", email="contacto@example.com",
                    )
                respuesta = self.client.get(reverse("inscripcion"))
                self.assertRedirects(respuesta, reverse("panel"))
                self.assertTemplateNotUsed(respuesta, "usuarios/inscripcion_form.html")
                self.assertFalse(SolicitudInscripcion.objects.exists())
                self.assertFalse(Jugador.objects.exists())

    def test_post_publico_no_crea_inscripcion_para_usuario_autenticado_o_apoderado(self):
        usuario = Usuario.objects.create_user(rut="20347119-K")
        self.client.force_login(usuario)
        for es_apoderado in (False, True):
            with self.subTest(es_apoderado=es_apoderado):
                if es_apoderado:
                    Apoderado.objects.create(
                        usuario=usuario, rut=usuario.rut, nombres="Cuenta", apellidos="Existente",
                        telefono="+56911111111", email="contacto@example.com",
                    )
                apoderados_antes = Apoderado.objects.count()
                respuesta = self.client.post(reverse("inscripcion"), self.datos_adulto())
                self.assertRedirects(respuesta, reverse("panel"))
                self.assertTemplateNotUsed(respuesta, "usuarios/inscripcion_form.html")
                self.assertFalse(SolicitudInscripcion.objects.exists())
                self.assertFalse(Jugador.objects.exists())
                self.assertFalse(ApoderadoJugador.objects.exists())
                self.assertFalse(AlertaSalud.objects.exists())
                self.assertEqual(Apoderado.objects.count(), apoderados_antes)
                self.assertEqual(Usuario.objects.count(), 1)
                self.assertNotIn("ultima_solicitud_id", self.client.session)

    def test_inscripcion_publica_adulto_no_crea_apoderado(self):
        respuesta = self.client.post(
            reverse("inscripcion"),
            self.datos_adulto(),
        )

        self.assertRedirects(respuesta, reverse("inscripcion_exito"))

        jugador = Jugador.objects.get(rut="11111111-1")
        solicitud = SolicitudInscripcion.objects.get(jugador=jugador)

        self.assertEqual(jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(jugador.categoria_actual.nombre, "Todo Competidor Varones")
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

    def datos_menor(self, **cambios):
        datos = self.datos_adulto(
            fecha_nacimiento="2012-03-10", email="", telefono="",
            nombre_contacto_emergencia="", telefono_contacto_emergencia="",
            rut_apoderado="12345678-5", nombres_apoderado="Patricia",
            apellidos_apoderado="Responsable", telefono_apoderado="+56955556666",
            email_apoderado="responsable@example.com", parentesco="MADRE",
        )
        datos.update(cambios)
        return datos

    def apoderado_existente(self, usuario=None):
        return Apoderado.objects.create(
            rut="12345678-5", nombres="Patricia", apellidos="Responsable",
            telefono="+56955556666", email="responsable@example.com", usuario=usuario,
        )

    def test_reutiliza_apoderado_publico_coherente_sin_modificarlo(self):
        apoderado = self.apoderado_existente()
        anterior = Apoderado.objects.values().get(pk=apoderado.pk)
        for rut in ("11111111-1", "22222222-2"):
            respuesta = self.client.post(reverse("inscripcion"), self.datos_menor(rut=rut))
            self.assertRedirects(respuesta, reverse("inscripcion_exito"))
        self.assertEqual(Apoderado.objects.count(), 1)
        self.assertEqual(Apoderado.objects.values().get(pk=apoderado.pk), anterior)
        self.assertEqual(set(ApoderadoJugador.objects.values_list("apoderado_id", flat=True)), {apoderado.pk})
        self.assertEqual(SolicitudInscripcion.objects.count(), 2)
        self.assertFalse(Usuario.objects.exists())

    def test_identidad_distinta_del_apoderado_publico_no_se_sobrescribe(self):
        apoderado = self.apoderado_existente()
        anterior = Apoderado.objects.values().get(pk=apoderado.pk)
        for campo in ("nombres_apoderado", "apellidos_apoderado", "telefono_apoderado", "email_apoderado"):
            with self.subTest(campo=campo):
                valor = "otro@example.com" if campo == "email_apoderado" else "Otro dato"
                respuesta = self.client.post(reverse("inscripcion"), self.datos_menor(**{campo: valor}))
                self.assertContains(respuesta, ERROR_IDENTIDAD_INSCRIPCION)
                self.assertFalse(Jugador.objects.exists())
                self.assertFalse(SolicitudInscripcion.objects.exists())
                self.assertEqual(Apoderado.objects.values().get(pk=apoderado.pk), anterior)

    def test_apoderado_con_cuenta_debe_usar_su_sesion(self):
        cuenta = Usuario.objects.create_user(rut="12345678-5", email="responsable@example.com")
        self.apoderado_existente(usuario=cuenta)
        respuesta = self.client.post(reverse("inscripcion"), self.datos_menor())
        self.assertContains(respuesta, ERROR_IDENTIDAD_INSCRIPCION)
        self.assertFalse(Jugador.objects.exists())

    def test_apoderado_autenticado_agrega_jugador_e_ignora_identidad_enviada(self):
        cuenta = Usuario.objects.create_user(rut="12345678-5", email="responsable@example.com")
        apoderado = self.apoderado_existente(usuario=cuenta)
        anterior = Apoderado.objects.values().get(pk=apoderado.pk)
        self.client.force_login(cuenta)
        ruta = reverse("agregar_jugador_apoderado")
        formulario = self.client.get(ruta).context["form"]
        self.assertNotIn("rut_apoderado", formulario.fields)
        datos = self.datos_menor(rut_apoderado="20347119-K", nombres_apoderado="Manipulado")
        respuesta = self.client.post(ruta, datos)
        self.assertRedirects(respuesta, reverse("panel"))
        solicitud = SolicitudInscripcion.objects.get()
        vinculo = ApoderadoJugador.objects.get()
        self.assertEqual(vinculo.apoderado_id, apoderado.pk)
        self.assertEqual(vinculo.parentesco, "MADRE")
        self.assertEqual(solicitud.solicitante_id, cuenta.pk)
        self.assertEqual(Apoderado.objects.values().get(pk=apoderado.pk), anterior)

    def test_cambio_correo_panel_permite_aprobar_otro_jugador(self):
        cuenta = Usuario.objects.create_user(
            rut="12345678-5", email="responsable@example.com", password="ClaveExistente123!",
        )
        apoderado = self.apoderado_existente(usuario=cuenta)
        self.assertEqual(cuenta.email, apoderado.email)
        self.client.force_login(cuenta)

        respuesta = self.client.post(reverse("panel"), {
            "accion": "contacto", "telefono": apoderado.telefono, "email": "nuevo@example.com",
            "rut": "20347119-K", "rut_apoderado": "20347119-K", "nombres": "Manipulado",
        })
        self.assertRedirects(respuesta, reverse("panel"))
        cuenta.refresh_from_db()
        apoderado.refresh_from_db()
        self.assertEqual(cuenta.email, "nuevo@example.com")
        self.assertEqual(apoderado.email, "nuevo@example.com")
        self.assertEqual(cuenta.rut, "12345678-5")
        self.assertEqual(apoderado.rut, "12345678-5")
        self.assertEqual(apoderado.nombres, "Patricia")
        self.assertEqual(apoderado.usuario_id, cuenta.pk)

        datos = self.datos_menor()
        for campo in ("rut_apoderado", "nombres_apoderado", "apellidos_apoderado",
                      "telefono_apoderado", "email_apoderado"):
            datos.pop(campo)
        respuesta = self.client.post(reverse("agregar_jugador_apoderado"), datos)
        self.assertRedirects(respuesta, reverse("panel"))
        solicitud = SolicitudInscripcion.objects.get()
        vinculo = ApoderadoJugador.objects.get(jugador=solicitud.jugador)
        self.assertEqual(vinculo.apoderado_id, apoderado.pk)
        self.assertEqual(vinculo.parentesco, "MADRE")
        self.assertEqual(solicitud.solicitante_id, cuenta.pk)

        actor = Usuario.objects.create_user(rut="20347119-K")
        actor.groups.add(Group.objects.get_or_create(name="Administración")[0])
        self.client.force_login(actor)
        detalle = reverse("solicitud_detalle", args=[solicitud.pk])
        respuesta = self.client.post(reverse("solicitud_iniciar_revision", args=[solicitud.pk]))
        self.assertRedirects(respuesta, detalle)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

        respuesta = self.client.post(reverse("solicitud_aprobar", args=[solicitud.pk]))
        self.assertRedirects(respuesta, detalle)
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.APROBADA)
        self.assertEqual(solicitud.usuario_autorizado_id, cuenta.pk)
        self.assertEqual(solicitud.jugador.estado, Jugador.Estado.ACTIVO)

    def test_error_al_guardar_cuenta_revierte_contacto_del_apoderado(self):
        cuenta = Usuario.objects.create_user(rut="12345678-5", email="responsable@example.com")
        apoderado = self.apoderado_existente(usuario=cuenta)
        anterior = Apoderado.objects.values().get(pk=apoderado.pk)
        self.client.force_login(cuenta)
        with patch("usuarios.models.Usuario.save", side_effect=ValidationError("Error controlado")):
            with self.assertRaises(ValidationError):
                self.client.post(reverse("panel"), {
                    "accion": "contacto", "telefono": "+56977778888", "email": "nuevo@example.com",
                })
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.email, "responsable@example.com")
        self.assertEqual(Apoderado.objects.values().get(pk=apoderado.pk), anterior)

    def test_agregar_jugador_exige_perfil_y_no_autoriza_otro_apoderado(self):
        cuenta = Usuario.objects.create_user(rut="20347119-K")
        apoderado = self.apoderado_existente()
        self.client.force_login(cuenta)
        respuesta = self.client.post(reverse("agregar_jugador_apoderado"), self.datos_menor())
        self.assertRedirects(respuesta, reverse("panel"))
        formulario = InscripcionJugadorForm(self.datos_menor())
        self.assertTrue(formulario.is_valid(), formulario.errors)
        with self.assertRaises(ValidationError):
            inscribir_jugador(datos=formulario.cleaned_data, solicitante=cuenta, apoderado_existente=apoderado)
        self.assertFalse(Jugador.objects.exists())

    def test_inscripcion_sin_categoria_revierte_toda_la_creacion(self):
        respuesta = self.client.post(reverse("inscripcion"), self.datos_menor(fecha_nacimiento="2024-03-10"))
        self.assertContains(respuesta, "No existe una categoría aplicable")
        self.assertFalse(Jugador.objects.exists())
        self.assertFalse(Apoderado.objects.exists())
        self.assertFalse(ApoderadoJugador.objects.exists())
        self.assertFalse(SolicitudInscripcion.objects.exists())
        self.assertFalse(Auditoria.objects.exists())

    def test_error_de_auditoria_revierte_inscripcion_y_alerta(self):
        with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Error controlado")):
            respuesta = self.client.post(reverse("inscripcion"), self.datos_menor(
                tiene_alerta_salud="SI", alerta_tipo="Alergia", alerta_descripcion="Dato reservado",
            ))
        self.assertEqual(respuesta.status_code, 200)
        for modelo in (Jugador, Apoderado, ApoderadoJugador, AlertaSalud, SolicitudInscripcion, Auditoria):
            self.assertFalse(modelo.objects.exists())

    def test_nuevos_formularios_bloquean_cruces_de_identidad_sin_exponer_datos(self):
        apoderado = self.apoderado_existente()
        respuesta = self.client.post(reverse("inscripcion"), self.datos_adulto(rut=apoderado.rut))
        self.assertContains(respuesta, ERROR_IDENTIDAD_INSCRIPCION)
        self.assertNotContains(respuesta, "Patricia")
        self.assertFalse(Jugador.objects.exists())

    def test_crear_solicitud_preserva_excepcion_manual(self):
        from .services import cambiar_categoria_manual
        formulario = InscripcionJugadorForm(self.datos_adulto())
        self.assertTrue(formulario.is_valid())
        solicitud = inscribir_jugador(datos=formulario.cleaned_data)
        jugador = solicitud.jugador
        actor = Usuario.objects.create_user(rut="20347119-K")
        categoria = Categoria.objects.get(nombre="U17 Varones")
        cambiar_categoria_manual(jugador, categoria, actor, "Autorización deportiva")
        historial = list(jugador.historial_categorias.order_by("pk").values())
        crear_solicitud_inscripcion(jugador=jugador, consentimiento=True)
        jugador.refresh_from_db()
        self.assertEqual(jugador.categoria_actual_id, categoria.pk)
        self.assertEqual(list(jugador.historial_categorias.order_by("pk").values()), historial)

    def test_agregar_adulto_conserva_vinculo_al_consultar_su_panel(self):
        cuenta = Usuario.objects.create_user(rut="12345678-5", email="responsable@example.com")
        apoderado = self.apoderado_existente(usuario=cuenta)
        self.client.force_login(cuenta)
        respuesta = self.client.post(reverse("agregar_jugador_apoderado"), self.datos_adulto(parentesco="TUTOR"))
        self.assertRedirects(respuesta, reverse("panel"))
        solicitud = SolicitudInscripcion.objects.get()
        vinculo = ApoderadoJugador.objects.get()
        self.assertEqual(vinculo.apoderado_id, apoderado.pk)
        self.assertEqual(vinculo.parentesco, "TUTOR")
        actor = Usuario.objects.create_user(rut="20347119-K")
        actor.groups.add(Group.objects.get_or_create(name="Administración")[0])
        cuenta_adulta = Usuario.objects.create_user(rut="11111111-1", email="alex@example.com", password="ClaveExistente123!")
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=actor)
        aprobada = aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=actor)
        self.assertEqual(aprobada.usuario_autorizado_id, cuenta_adulta.pk)
        anterior = ApoderadoJugador.objects.values().get(pk=vinculo.pk)
        self.client.force_login(cuenta_adulta)
        self.assertRedirects(self.client.get(reverse("panel")), reverse("panel_jugador"))
        self.assertEqual(ApoderadoJugador.objects.values().get(pk=vinculo.pk), anterior)

    def test_no_asume_parentesco_omitido_en_post_autenticado(self):
        apoderado = self.apoderado_existente()
        formulario = InscripcionJugadorForm(self.datos_menor(parentesco=""), apoderado_existente=apoderado)
        self.assertFalse(formulario.is_valid())
        self.assertIn("parentesco", formulario.errors)


class GestionSolicitudesSprint2Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

        cls.administracion = Usuario.objects.create_user(
            rut="20347119-K",
            is_staff=False,
        )
        cls.administracion.groups.add(Group.objects.get_or_create(name="Administración")[0])
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

    def test_administracion_sin_staff_accede_a_listado_y_detalle(self):
        self.assertFalse(self.administracion.is_staff)
        self.assertTrue(self.administracion.groups.exists())
        self.client.force_login(self.administracion)

        listado = self.client.get(reverse("solicitudes_administracion"))
        detalle = self.client.get(
            reverse("solicitud_detalle", args=[self.solicitud.pk]),
        )

        self.assertEqual(listado.status_code, 200)
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(listado, "Jugador En revisión")
        self.assertContains(detalle, "Solicitud #")

    def test_usuario_sin_grupo_no_accede_ni_cambia_estado(self):
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
        self.client.force_login(self.administracion)

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
        self.assertEqual(solicitud.revisado_por, self.administracion)
        self.assertIsNotNone(solicitud.fecha_revision)
        self.assertEqual(jugador.estado, Jugador.Estado.ACTIVO)
        self.assertIsNotNone(jugador.fecha_ingreso)
        self.assertTrue(
            Auditoria.objects.filter(
                accion="SOLICITUD_APROBADA",
                entidad_id=solicitud.pk,
                usuario=self.administracion,
            ).exists(),
        )

    def test_rechazo_exige_motivo_y_registra_el_valido(self):
        self.client.force_login(self.administracion)
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
        self.assertEqual(solicitud.revisado_por, self.administracion)
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
                usuario=self.administracion,
            ).exists(),
        )

    def test_lista_muestra_accion_por_estado_y_get_no_lo_cambia(self):
        self.client.force_login(self.administracion)
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
        self.client.force_login(self.administracion)
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
        cliente.force_login(self.administracion)
        cliente.get(reverse("solicitudes_administracion"))
        ruta = reverse("solicitud_iniciar_revision", args=[self.solicitud.pk])
        self.assertEqual(cliente.post(ruta).status_code, 403)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)

        respuesta = cliente.post(ruta, {"csrfmiddlewaretoken": cliente.cookies["csrftoken"].value})

        self.assertRedirects(respuesta, reverse("solicitud_detalle", args=[self.solicitud.pk]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

    def test_revision_exige_actor_administrativo_en_servicio(self):
        for usuario in (self.usuario_sin_permiso, self.administracion):
            if usuario == self.administracion:
                usuario.is_active = False
            with self.subTest(usuario=usuario.pk):
                with self.assertRaises(ValidationError):
                    marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=usuario)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_revision_rechaza_actor_ausente_o_anonimo_en_servicio(self):
        for usuario in (None, AnonymousUser()):
            with self.subTest(usuario=usuario):
                with self.assertRaises(ValidationError):
                    marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=usuario)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)

    def test_revision_confia_solo_en_estado_y_datos_persistidos(self):
        self.solicitud.estado = SolicitudInscripcion.Estado.APROBADA
        self.solicitud.observaciones = "Dato de una instancia desactualizada"
        revisada = marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=self.administracion)
        self.solicitud.refresh_from_db()
        self.assertEqual(revisada.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(self.solicitud.observaciones, "")

    def test_revision_desactualizada_no_sobrescribe_otra_revision(self):
        vieja = SolicitudInscripcion.objects.get(pk=self.solicitud.pk)
        marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=self.administracion)
        anterior = SolicitudInscripcion.objects.values().get(pk=self.solicitud.pk)
        with self.assertRaises(ValidationError):
            marcar_solicitud_en_revision(solicitud=vieja, usuario=self.administracion)
        self.assertEqual(SolicitudInscripcion.objects.values().get(pk=self.solicitud.pk), anterior)

    def test_staff_y_superusuario_sin_grupo_no_autorizan_el_flujo(self):
        cuenta = self.usuario_sin_permiso
        cuenta.is_staff = True
        cuenta.is_superuser = True
        cuenta.save()
        self.client.force_login(cuenta)
        for nombre in ("solicitudes_administracion", "solicitud_detalle"):
            args = [] if nombre == "solicitudes_administracion" else [self.solicitud.pk]
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 302)
        for nombre in ("solicitud_iniciar_revision", "solicitud_aprobar", "solicitud_rechazar"):
            self.assertEqual(self.client.post(reverse(nombre, args=[self.solicitud.pk]), {"motivo": "Motivo"}).status_code, 302)
        for servicio, extras in ((marcar_solicitud_en_revision, {}), (aprobar_solicitud_inscripcion, {}),
                                 (rechazar_solicitud_inscripcion, {"motivo": "Motivo"})):
            with self.assertRaises(ValidationError):
                servicio(solicitud=self.solicitud, usuario=cuenta, **extras)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)

    def test_aprobar_y_rechazar_exigen_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.administracion)
        marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=self.administracion)
        for nombre in ("solicitud_aprobar", "solicitud_rechazar"):
            self.assertEqual(cliente.post(reverse(nombre, args=[self.solicitud.pk]), {"motivo": "Motivo"}).status_code, 403)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(self.solicitud.usuario_autorizado_id)

    def test_no_se_puede_resolver_directamente_una_solicitud_pendiente(self):
        for servicio, extras in ((aprobar_solicitud_inscripcion, {}),
                                 (rechazar_solicitud_inscripcion, {"motivo": "Motivo"})):
            with self.assertRaises(ValidationError):
                servicio(solicitud=self.solicitud, usuario=self.administracion, **extras)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)
        self.assertFalse(Auditoria.objects.exists())

    def test_endpoints_antiguos_no_resuelven_ni_activan(self):
        self.client.force_login(self.administracion)
        respuesta = self.client.get(reverse("validar_fichas"))
        self.assertRedirects(respuesta, reverse("solicitudes_administracion"))
        self.assertEqual(self.client.post(reverse("validar_fichas"), {
            "solicitud_id": self.solicitud.pk, "accion": "aprobar",
        }).status_code, 405)
        for metodo in (self.client.get, self.client.post):
            self.assertEqual(metodo("/activar-jugador/").status_code, 404)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)

    def test_rechazo_desactualizado_no_duplica_auditoria(self):
        vieja = SolicitudInscripcion.objects.get(pk=self.solicitud.pk)
        marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=self.administracion)
        rechazar_solicitud_inscripcion(solicitud=self.solicitud, usuario=self.administracion, motivo="Antecedentes incompletos")
        anterior = SolicitudInscripcion.objects.values().get(pk=self.solicitud.pk)
        with self.assertRaises(ValidationError):
            rechazar_solicitud_inscripcion(solicitud=vieja, usuario=self.administracion, motivo="Otro motivo")
        self.assertEqual(SolicitudInscripcion.objects.values().get(pk=self.solicitud.pk), anterior)
        self.assertEqual(Auditoria.objects.filter(accion="SOLICITUD_RECHAZADA").count(), 1)

    def test_error_de_auditoria_revierte_rechazo(self):
        marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=self.administracion)
        anterior = SolicitudInscripcion.objects.values().get(pk=self.solicitud.pk)
        with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Error controlado")):
            with self.assertRaises(ValidationError):
                rechazar_solicitud_inscripcion(solicitud=self.solicitud, usuario=self.administracion, motivo="Motivo válido")
        self.assertEqual(SolicitudInscripcion.objects.values().get(pk=self.solicitud.pk), anterior)
        self.assertFalse(Auditoria.objects.filter(accion="SOLICITUD_RECHAZADA").exists())

    def test_conflicto_de_integridad_en_aprobacion_no_deja_resolucion_parcial(self):
        from django.db import IntegrityError
        self.client.force_login(self.administracion)
        marcar_solicitud_en_revision(solicitud=self.solicitud, usuario=self.administracion)
        with patch("usuarios.services.Usuario.objects.create_user", side_effect=IntegrityError("Conflicto controlado")):
            respuesta = self.client.post(reverse("solicitud_aprobar", args=[self.solicitud.pk]))
        self.assertRedirects(respuesta, reverse("solicitud_detalle", args=[self.solicitud.pk]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(self.solicitud.usuario_autorizado_id)
        self.assertFalse(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").exists())
