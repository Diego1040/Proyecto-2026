import re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth.models import Group
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import AlertaSalud, Apoderado, ApoderadoJugador, Auditoria, Categoria, Jugador, SolicitudInscripcion, Usuario
from .services import aprobar_solicitud_inscripcion, marcar_solicitud_en_revision, rechazar_solicitud_inscripcion
from .tokens import activacion_token_generator
from .views import ConfirmarActivacionView


@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
class ActivacionCuentasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        cls.administracion = Usuario.objects.create_user(
            rut="20347119-K", password="ClaveAdministrativa123!",
        )

        cls.administracion.groups.add(Group.objects.get_or_create(name="Administración")[0])

    def setUp(self):
        cache.clear()

    def solicitud(self, *, rut="11111111-1", nacimiento=date(1990, 3, 10),
                  email="adulto@example.com", apoderado=None, principal=True,
                  correo_apoderado="responsable@example.com"):
        jugador = Jugador.objects.create(
            rut=rut, nombres="Alex", apellidos="Deportista",
            fecha_nacimiento=nacimiento, rama=Jugador.Rama.VARONES,
            email=email, categoria_actual=Categoria.objects.get(nombre="Todo Competidor Varones"),
        )
        if nacimiento > date(timezone.localdate().year - 18, timezone.localdate().month, timezone.localdate().day):
            if apoderado is None:
                apoderado = Apoderado.objects.create(
                    rut="12345678-5", nombres="Patricia", apellidos="Responsable",
                    telefono="+56911111111", email=correo_apoderado,
                )
            ApoderadoJugador.objects.create(
                jugador=jugador, apoderado=apoderado, parentesco="MADRE",
                es_principal=principal, puede_gestionar=True,
            )
        solicitud = SolicitudInscripcion.objects.create(
            jugador=jugador, procedencia=Jugador.Procedencia.INDEPENDIENTE,
            consentimiento=True,
        )
        return solicitud

    def aprobar(self, solicitud, *, request=None):
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        return aprobar_solicitud_inscripcion(
            solicitud=solicitud, usuario=self.administracion,
            request=request or RequestFactory().get("/"),
        )

    def enlace_aprobacion(self, solicitud):
        with self.captureOnCommitCallbacks(execute=True):
            aprobada = self.aprobar(solicitud)
        enlace = re.search(r"https?://\S+", mail.outbox[-1].body).group(0)
        return aprobada.usuario_autorizado, urlparse(enlace).path

    def test_correo_de_aprobacion_se_envia_despues_del_commit(self):
        solicitud = self.solicitud()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.aprobar(solicitud)
            self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/activar-cuenta/", mail.outbox[0].body)

    def test_rollback_externo_descarta_aprobacion_y_correo(self):
        solicitud = self.solicitud()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(ValidationError):
                with transaction.atomic():
                    self.aprobar(solicitud)
                    raise ValidationError("Cancelar transacción externa")
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertEqual(Usuario.objects.count(), 1)
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_solicitud_valida_reenvia_y_respuesta_desconocida_es_generica(self):
        solicitud = self.solicitud()
        cuenta, _ = self.enlace_aprobacion(solicitud)
        mail.outbox.clear()
        datos = {"rut": cuenta.rut, "email": cuenta.email}
        with self.captureOnCommitCallbacks(execute=True):
            valida = self.client.post(reverse("activar_cuenta"), datos, follow=True)
        self.assertEqual(len(mail.outbox), 1)
        with self.captureOnCommitCallbacks(execute=True):
            invalida = self.client.post(
                reverse("activar_cuenta"), {"rut": "33333333-3", "email": cuenta.email}, follow=True,
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(valida.content, invalida.content)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("activar_cuenta"), datos)
        self.assertEqual(len(mail.outbox), 1)
        cache.delete(f"activacion-reenvio:{cuenta.pk}")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("activar_cuenta"), datos)
        self.assertEqual(len(mail.outbox), 2)

    def test_pendiente_o_en_revision_no_puede_pedir_enlace(self):
        solicitud = self.solicitud()
        for estado in (SolicitudInscripcion.Estado.PENDIENTE, SolicitudInscripcion.Estado.EN_REVISION):
            if estado == SolicitudInscripcion.Estado.EN_REVISION:
                marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse("activar_cuenta"), {
                    "rut": solicitud.jugador.rut, "email": solicitud.jugador.email,
                })
            self.assertEqual(len(mail.outbox), 0)

    def test_token_valido_activa_y_permita_ingresar_sin_guardar_texto_plano(self):
        cuenta, ruta = self.enlace_aprobacion(self.solicitud())
        primer_paso = self.client.get(ruta)
        self.assertEqual(primer_paso.status_code, 302)
        formulario = self.client.get(primer_paso.url)
        self.assertContains(formulario, "Crear contraseña")
        clave = "ClavePropiaMuySegura123!"
        respuesta = self.client.post(primer_paso.url, {
            "new_password1": clave, "new_password2": clave,
        })
        self.assertRedirects(respuesta, reverse("activacion_completa"))
        cuenta.refresh_from_db()
        self.assertTrue(cuenta.is_active)
        self.assertIsNotNone(cuenta.activado_en)
        self.assertNotEqual(cuenta.password, clave)
        self.assertTrue(cuenta.check_password(clave))
        login = self.client.post(reverse("login"), {"username": cuenta.rut, "password": clave})
        self.assertRedirects(login, reverse("panel"))

    def test_token_invalido_vencido_y_utilizado_no_activan(self):
        cuenta, ruta = self.enlace_aprobacion(self.solicitud())
        invalido = self.client.get(ruta.replace(ruta.split("/")[-2], "invalido"))
        self.assertContains(invalido, "Enlace no disponible")
        with override_settings(PASSWORD_RESET_TIMEOUT=1):
            with patch.object(activacion_token_generator, "_now", return_value=datetime.now() + timedelta(days=2)):
                vencido = self.client.get(ruta)
        self.assertContains(vencido, "Enlace no disponible")
        cuenta.refresh_from_db()
        self.assertFalse(cuenta.is_active)
        paso = self.client.get(ruta)
        self.client.post(paso.url, {
            "new_password1": "ClavePropiaMuySegura123!",
            "new_password2": "ClavePropiaMuySegura123!",
        })
        usado = self.client.get(ruta)
        self.assertContains(usado, "Enlace no disponible")
        cantidad = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("activar_cuenta"), {"rut": cuenta.rut, "email": cuenta.email})
        self.assertEqual(len(mail.outbox), cantidad)

    def test_login_muestra_activar_mi_cuenta(self):
        self.assertContains(self.client.get(reverse("login")), reverse("activar_cuenta"))

    def test_token_nativo_de_recuperacion_no_activa_cuenta_pendiente(self):
        cuenta, _ = self.enlace_aprobacion(self.solicitud())
        token = default_token_generator.make_token(cuenta)
        self.assertTrue(default_token_generator.check_token(cuenta, token))
        self.assertFalse(activacion_token_generator.check_token(cuenta, token))
        anterior = (cuenta.password, cuenta.is_active, cuenta.activado_en)
        ruta = reverse("confirmar_activacion", kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(cuenta.pk)), "token": token,
        })
        self.assertContains(self.client.get(ruta), "Enlace no disponible")
        self.assertContains(self.client.post(ruta, {
            "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
        }), "Enlace no disponible")
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.password, cuenta.is_active, cuenta.activado_en), anterior)

    def test_token_emitido_de_activacion_no_funciona_en_recuperacion(self):
        cuenta, ruta_activacion = self.enlace_aprobacion(self.solicitud())
        token = ruta_activacion.split("/")[-2]
        self.assertTrue(activacion_token_generator.check_token(cuenta, token))
        self.assertFalse(default_token_generator.check_token(cuenta, token))
        anterior = (cuenta.password, cuenta.is_active, cuenta.activado_en)
        ruta = reverse("password_reset_confirm", kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(cuenta.pk)), "token": token,
        })
        self.assertContains(self.client.get(ruta), "Enlace no disponible")
        self.assertContains(self.client.post(ruta, {
            "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
        }), "Enlace no disponible")
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.password, cuenta.is_active, cuenta.activado_en), anterior)

    def test_notificacion_de_cuenta_activa_no_incluye_datos_sensibles(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com", password="ClaveExistente123!",
        )
        credenciales = (cuenta.password, cuenta.email, cuenta.is_active, cuenta.activado_en)
        solicitud = self.solicitud()
        jugador = solicitud.jugador
        jugador.peso_kg, jugador.talla_cm = 72, 180
        jugador.save()
        AlertaSalud.objects.create(jugador=jugador, tipo="AlergiaReservada", descripcion="Información médica reservada")
        solicitud.observaciones = "ObservaciónReservada"
        solicitud.save(update_fields=["observaciones"])
        with self.captureOnCommitCallbacks(execute=True):
            self.aprobar(solicitud)
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.password, cuenta.email, cuenta.is_active, cuenta.activado_en), credenciales)
        self.assertEqual(len(mail.outbox), 1)
        texto = mail.outbox[0].subject + mail.outbox[0].body
        self.assertIn("jugador", texto)
        self.assertIn("aprobada", texto)
        for reservado in (jugador.rut, jugador.nombres, jugador.apellidos, "AlergiaReservada",
                          "Información médica reservada", "ObservaciónReservada", "peso", "talla", "/activar-cuenta/"):
            self.assertNotIn(reservado, texto)

    def test_rollback_descarta_notificacion_de_cuenta_activa(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com", password="ClaveExistente123!",
        )
        clave = cuenta.password
        solicitud = self.solicitud()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(ValidationError):
                with transaction.atomic():
                    self.aprobar(solicitud)
                    raise ValidationError("Cancelar aprobación")
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        cuenta.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.PENDIENTE)
        self.assertIsNone(solicitud.usuario_autorizado_id)
        self.assertIsNone(solicitud.jugador.usuario_id)
        self.assertEqual(cuenta.password, clave)
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Auditoria.objects.exists())

    def test_aprobacion_repetida_no_duplica_notificacion_de_cuenta_activa(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com", password="ClaveExistente123!",
        )
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        vieja = SolicitudInscripcion.objects.get(pk=solicitud.pk)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
            anterior = SolicitudInscripcion.objects.values().get(pk=solicitud.pk)
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=vieja, usuario=self.administracion)
            self.assertEqual(SolicitudInscripcion.objects.values().get(pk=solicitud.pk), anterior)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cuenta.email])
        self.assertEqual(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").count(), 1)

    def test_aprobacion_desde_vista_envia_al_apoderado_y_activacion_permite_login(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="")
        self.client.force_login(self.administracion)
        self.client.post(reverse("solicitud_iniciar_revision", args=[solicitud.pk]))
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(reverse("solicitud_aprobar", args=[solicitud.pk]))
        self.assertRedirects(respuesta, reverse("solicitud_detalle", args=[solicitud.pk]))
        solicitud.refresh_from_db()
        cuenta = solicitud.usuario_autorizado
        apoderado = solicitud.jugador.vinculos_apoderados.get().apoderado
        self.assertEqual(cuenta.pk, apoderado.usuario_id)
        self.assertIsNone(solicitud.jugador.usuario_id)
        self.assertEqual(mail.outbox[0].to, [apoderado.email])
        self.assertFalse(cuenta.is_active)
        self.assertFalse(cuenta.has_usable_password())
        self.client.logout()
        enlace = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
        self.assertEqual(urlparse(enlace).netloc, "testserver")
        paso = self.client.get(urlparse(enlace).path)
        cuenta.refresh_from_db()
        self.assertFalse(cuenta.is_active)
        self.assertFalse(cuenta.has_usable_password())
        clave = "ClaveApoderadoMuySegura123!"
        self.assertRedirects(self.client.post(paso.url, {
            "new_password1": clave, "new_password2": clave,
        }), reverse("activacion_completa"))
        self.assertRedirects(self.client.post(reverse("login"), {
            "username": cuenta.rut, "password": clave,
        }), reverse("panel"))
        self.assertContains(self.client.get(reverse("panel")), reverse("perfil_apoderado"))
        self.assertNotContains(self.client.get(reverse("panel")), reverse("perfil_jugador"))

    def test_cuenta_suspendida_no_recibe_reenvio_ni_se_activa_con_enlace_previo(self):
        cuenta, ruta = self.enlace_aprobacion(self.solicitud())
        paso = self.client.get(ruta)
        Usuario.objects.filter(pk=cuenta.pk).update(activado_en=timezone.now())
        cuenta.refresh_from_db()
        anterior = (cuenta.password, cuenta.is_active, cuenta.activado_en)
        cantidad = len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(reverse("activar_cuenta"), {
                "rut": cuenta.rut, "email": cuenta.email,
            }, follow=True)
        self.assertContains(respuesta, "Si los datos corresponden")
        self.assertEqual(len(mail.outbox), cantidad)
        self.assertContains(self.client.post(paso.url, {
            "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
        }), "Enlace no disponible")
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.password, cuenta.is_active, cuenta.activado_en), anterior)

    def test_token_se_revalida_bajo_bloqueo_si_el_correo_cambia_durante_post(self):
        cuenta, ruta = self.enlace_aprobacion(self.solicitud())
        paso = self.client.get(ruta)
        anterior = cuenta.password
        guardar = ConfirmarActivacionView.form_valid

        def cambiar_correo_antes_de_guardar(vista, formulario):
            Usuario.objects.filter(pk=vista.user.pk).update(email="otro@example.com")
            return guardar(vista, formulario)

        with patch.object(ConfirmarActivacionView, "form_valid", cambiar_correo_antes_de_guardar):
            respuesta = self.client.post(paso.url, {
                "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
            })
        self.assertContains(respuesta, "Enlace no disponible")
        cuenta.refresh_from_db()
        self.assertFalse(cuenta.is_active)
        self.assertIsNone(cuenta.activado_en)
        self.assertEqual(cuenta.password, anterior)

    def test_error_de_guardado_revierte_toda_la_activacion(self):
        cuenta, ruta = self.enlace_aprobacion(self.solicitud())
        paso = self.client.get(ruta)
        anterior = Usuario.objects.values().get(pk=cuenta.pk)
        with patch("usuarios.models.Usuario.save", side_effect=ValidationError("Fallo controlado")):
            respuesta = self.client.post(paso.url, {
                "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
            })
        self.assertContains(respuesta, "Enlace no disponible")
        self.assertEqual(Usuario.objects.values().get(pk=cuenta.pk), anterior)

    def test_activacion_exige_clave_segura_y_csrf(self):
        cuenta, ruta = self.enlace_aprobacion(self.solicitud())
        cliente = Client(enforce_csrf_checks=True)
        self.assertEqual(cliente.post(reverse("activar_cuenta"), {
            "rut": cuenta.rut, "email": cuenta.email,
        }).status_code, 403)
        paso = cliente.get(ruta)
        self.assertEqual(cliente.post(paso.url, {
            "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
        }).status_code, 403)
        paso = self.client.get(ruta)
        respuesta = self.client.post(paso.url, {"new_password1": "abc", "new_password2": "abc"})
        self.assertTrue(respuesta.context["form"].errors)
        cuenta.refresh_from_db()
        self.assertFalse(cuenta.is_active)
        self.assertFalse(cuenta.has_usable_password())

    def test_rechazo_notifica_al_titular_despues_del_commit_sin_datos_sensibles(self):
        for rut, nacimiento, destinatario in (
            ("11111111-1", date(1990, 3, 10), "adulto@example.com"),
            ("22222222-2", date(2013, 3, 10), "responsable@example.com"),
        ):
            with self.subTest(nacimiento=nacimiento):
                solicitud = self.solicitud(rut=rut, nacimiento=nacimiento)
                AlertaSalud.objects.create(jugador=solicitud.jugador, tipo="Privado", descripcion="SaludReservada")
                marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
                cantidad = len(mail.outbox)
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    rechazar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion,
                                                  motivo="Falta documentación")
                    self.assertEqual(len(mail.outbox), cantidad)
                self.assertEqual(len(callbacks), 1)
                self.assertEqual(mail.outbox[-1].to, [destinatario])
                self.assertIn("Falta documentación", mail.outbox[-1].body)
                for reservado in (rut, "SaludReservada", "Privado", "Alex", "Deportista"):
                    self.assertNotIn(reservado, mail.outbox[-1].body)

    def test_rollback_descarta_correo_de_rechazo(self):
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(ValidationError):
                with transaction.atomic():
                    rechazar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion, motivo="Falta documento")
                    raise ValidationError("Cancelar rechazo")
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

    def test_rechazo_historico_sin_correo_se_conserva_sin_notificacion(self):
        solicitud = self.solicitud(email="")
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            rechazar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion, motivo="Falta documento")
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.RECHAZADA)
