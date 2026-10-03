import re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import Apoderado, Jugador, SolicitudInscripcion, Usuario
from .services import aprobar_solicitud_inscripcion, marcar_solicitud_en_revision
from .tokens import activacion_token_generator
from .views import ConfirmarRecuperacionView


@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
class RecuperacionConDjangoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="alex@example.com",
            password="ClaveAnteriorMuySegura123!", activado_en=timezone.now(),
        )

    def solicitar_enlace(self):
        respuesta = self.client.post(
            reverse("password_reset"), {"email": self.cuenta.email},
        )
        self.assertRedirects(respuesta, reverse("password_reset_done"))
        enlace = re.search(r"https?://\S+", mail.outbox[-1].body).group(0)
        return urlparse(enlace).path

    def test_login_ofrece_recuperacion_y_cuenta_activa_cambia_clave(self):
        self.assertContains(self.client.get(reverse("login")), reverse("password_reset"))
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)
        ruta = self.solicitar_enlace()
        self.assertEqual(len(mail.outbox), 1)
        paso = self.client.get(ruta)
        self.assertEqual(paso.status_code, 302)
        nueva_clave = "NuevaClaveMuySegura123!"
        respuesta = self.client.post(paso.url, {
            "new_password1": nueva_clave,
            "new_password2": nueva_clave,
        })
        self.assertRedirects(respuesta, reverse("password_reset_complete"))
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.is_active)
        self.assertNotEqual(self.cuenta.password, nueva_clave)
        self.assertTrue(self.cuenta.check_password(nueva_clave))
        self.assertContains(self.client.get(ruta), "Enlace no disponible")
        login = self.client.post(reverse("login"), {
            "username": self.cuenta.rut, "password": nueva_clave,
        })
        self.assertRedirects(login, reverse("panel"))

    def test_respuesta_generica_y_exclusion_de_inactivos_sin_clave(self):
        activa = self.client.post(
            reverse("password_reset"), {"email": self.cuenta.email}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        desconocida = self.client.post(
            reverse("password_reset"), {"email": "nadie@example.com"}, follow=True,
        )
        self.assertEqual(activa.content, desconocida.content)
        self.assertEqual(len(mail.outbox), 1)
        Usuario.objects.create_user(
            rut="22222222-2", email="inactiva@example.com",
            password="ClaveInactiva123!", is_active=False,
        )
        Usuario.objects.create_user(
            rut="33333333-3", email="sinclave@example.com",
            is_active=True,
        )
        for correo in ("inactiva@example.com", "sinclave@example.com"):
            respuesta = self.client.post(
                reverse("password_reset"), {"email": correo}, follow=True,
            )
            self.assertEqual(respuesta.content, activa.content)
            self.assertEqual(len(mail.outbox), 1)

    def test_token_invalido_y_vencido_no_cambian_clave(self):
        ruta = self.solicitar_enlace()
        invalida = self.client.get(ruta.replace(ruta.split("/")[-2], "invalido"))
        self.assertContains(invalida, "Enlace no disponible")
        with override_settings(PASSWORD_RESET_TIMEOUT=1):
            with patch.object(default_token_generator, "_now", return_value=datetime.now() + timedelta(days=2)):
                vencida = self.client.get(ruta)
        self.assertContains(vencida, "Enlace no disponible")
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.check_password("ClaveAnteriorMuySegura123!"))

    def test_validadores_nativos_rechazan_clave_debil(self):
        ruta = self.solicitar_enlace()
        paso = self.client.get(ruta)
        respuesta = self.client.post(paso.url, {
            "new_password1": "abc", "new_password2": "abc",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["form"].errors)
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.check_password("ClaveAnteriorMuySegura123!"))

    def test_recuperacion_rechaza_token_de_activacion_incluso_con_cuenta_elegible(self):
        token = activacion_token_generator.make_token(self.cuenta)
        self.assertFalse(default_token_generator.check_token(self.cuenta, token))
        anterior = (self.cuenta.password, self.cuenta.is_active, self.cuenta.activado_en)
        ruta = reverse("password_reset_confirm", kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(self.cuenta.pk)), "token": token,
        })
        self.assertContains(self.client.get(ruta), "Enlace no disponible")
        self.assertContains(self.client.post(ruta, {
            "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
        }), "Enlace no disponible")
        self.cuenta.refresh_from_db()
        self.assertEqual((self.cuenta.password, self.cuenta.is_active, self.cuenta.activado_en), anterior)

    def test_cuenta_deshabilitada_no_puede_usar_enlace_previo_antes_o_despues_del_get(self):
        for antes_del_get in (True, False):
            with self.subTest(antes_del_get=antes_del_get):
                Usuario.objects.filter(pk=self.cuenta.pk).update(is_active=True)
                self.cuenta.refresh_from_db()
                ruta = self.solicitar_enlace()
                token = ruta.split("/")[-2]
                if not antes_del_get:
                    paso = self.client.get(ruta)
                    self.assertEqual(paso.status_code, 302)
                    ruta = paso.url
                Usuario.objects.filter(pk=self.cuenta.pk).update(is_active=False)
                self.cuenta.refresh_from_db()
                anterior = (self.cuenta.password, self.cuenta.is_active, self.cuenta.activado_en)
                # El token nativo sigue siendo válido; la elegibilidad debe impedir su uso.
                self.assertTrue(default_token_generator.check_token(self.cuenta, token))
                self.assertContains(self.client.get(ruta), "Enlace no disponible")
                self.assertContains(self.client.post(ruta, {
                    "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
                }), "Enlace no disponible")
                self.cuenta.refresh_from_db()
                self.assertEqual((self.cuenta.password, self.cuenta.is_active, self.cuenta.activado_en), anterior)

    def test_perdida_de_elegibilidad_durante_post_se_comprueba_antes_de_guardar(self):
        ruta = self.solicitar_enlace()
        paso = self.client.get(ruta)
        anterior = (self.cuenta.password, self.cuenta.activado_en)
        guardar = ConfirmarRecuperacionView.form_valid

        def deshabilitar_antes_de_guardar(vista, formulario):
            Usuario.objects.filter(pk=vista.user.pk).update(is_active=False)
            return guardar(vista, formulario)

        with patch.object(ConfirmarRecuperacionView, "form_valid", deshabilitar_antes_de_guardar):
            respuesta = self.client.post(paso.url, {
                "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
            })
        self.assertContains(respuesta, "Enlace no disponible")
        self.cuenta.refresh_from_db()
        self.assertFalse(self.cuenta.is_active)
        self.assertEqual((self.cuenta.password, self.cuenta.activado_en), anterior)

    def test_cuenta_sin_clave_utilizable_no_puede_usar_enlace_previo(self):
        ruta = self.solicitar_enlace()
        paso = self.client.get(ruta)
        self.cuenta.set_unusable_password()
        self.cuenta.save(update_fields=["password"])
        anterior = (self.cuenta.password, self.cuenta.is_active, self.cuenta.activado_en)
        self.assertContains(self.client.post(paso.url, {
            "new_password1": "ClaveNuevaMuySegura123!", "new_password2": "ClaveNuevaMuySegura123!",
        }), "Enlace no disponible")
        self.cuenta.refresh_from_db()
        self.assertEqual((self.cuenta.password, self.cuenta.is_active, self.cuenta.activado_en), anterior)


@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
class CorreoApoderadoAntiguoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        cls.staff = Usuario.objects.create_superuser(
            rut="20347119-K", password="ClaveAdministrativa123!",
        )
        cls.cuenta = Usuario.objects.create_user(
            rut="12345678-5", email="", password="ClaveExistenteMuySegura123!",
            activado_en=timezone.now(),
        )
        cls.apoderado = Apoderado.objects.create(
            usuario=cls.cuenta, rut=cls.cuenta.rut,
            nombres="Patricia", apellidos="Responsable",
            telefono="+56911111111", email="",
        )

    def test_completa_contacto_sin_cambiar_correo_de_cuenta(self):
        self.client.force_login(self.cuenta)
        respuesta = self.client.post(reverse("perfil_apoderado"), {
            "accion": "guardar_correo", "email": "contacto@example.com",
            "usuario_id": self.staff.pk,
        })
        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        self.apoderado.refresh_from_db()
        self.cuenta.refresh_from_db()
        self.assertEqual(self.apoderado.email, "contacto@example.com")
        self.assertEqual(self.cuenta.email, "")
        recuperacion = self.client.post(
            reverse("password_reset"), {"email": "contacto@example.com"},
        )
        self.assertRedirects(recuperacion, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_cuenta_activa_sin_correo_reutiliza_acceso_al_inscribir_menor(self):
        self.client.force_login(self.cuenta)
        self.client.post(reverse("perfil_apoderado"), {
            "accion": "guardar_correo", "email": "contacto@example.com",
        })
        datos = {
            "rut": "22222222-2", "nombres": "Hija", "apellidos": "Deportista",
            "fecha_nacimiento": date(2013, 3, 10).isoformat(),
            "rama": Jugador.Rama.VARONES, "telefono": "", "email": "",
            "procedencia": Jugador.Procedencia.INDEPENDIENTE,
            "parentesco": "MADRE", "tiene_alerta_salud": "NO",
            "consentimiento": "on",
        }
        respuesta = self.client.post(reverse("agregar_jugador_apoderado"), datos)
        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        solicitud = SolicitudInscripcion.objects.get(jugador__rut="22222222-2")
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        clave_original = self.cuenta.password
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aprobada = aprobar_solicitud_inscripcion(
                solicitud=solicitud, usuario=self.staff,
            )
        self.cuenta.refresh_from_db()
        self.assertEqual(aprobada.usuario_autorizado_id, self.cuenta.pk)
        self.assertEqual(self.cuenta.password, clave_original)
        self.assertEqual(self.cuenta.email, "")
        self.assertTrue(self.cuenta.is_active)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["contacto@example.com"])
        self.assertIn("cuenta habitual", mail.outbox[0].body)
        self.assertNotIn("/activar-cuenta/", mail.outbox[0].body)
        self.assertIsNone(aprobada.jugador.usuario_id)

    def test_cuenta_con_correo_exige_coincidencia_y_no_modifica_usuario(self):
        self.cuenta.email = "registrado@example.com"
        self.cuenta.save(update_fields=["email"])
        self.client.force_login(self.cuenta)
        invalida = self.client.post(reverse("perfil_apoderado"), {
            "accion": "guardar_correo", "email": "otro@example.com",
        })
        self.assertEqual(invalida.status_code, 200)
        self.apoderado.refresh_from_db()
        self.assertEqual(self.apoderado.email, "")
        valida = self.client.post(reverse("perfil_apoderado"), {
            "accion": "guardar_correo", "email": "registrado@example.com",
        })
        self.assertRedirects(valida, reverse("perfil_apoderado"))
        self.apoderado.refresh_from_db()
        self.cuenta.refresh_from_db()
        self.assertEqual(self.apoderado.email, self.cuenta.email)

    def test_no_permite_editar_el_contacto_de_otro_apoderado(self):
        otro_usuario = Usuario.objects.create_user(
            rut="33333333-3", email="otro@example.com",
            password="OtraClaveMuySegura123!",
        )
        otro = Apoderado.objects.create(
            usuario=otro_usuario, rut=otro_usuario.rut,
            nombres="Otra", apellidos="Persona", telefono="+56922222222",
        )
        self.client.force_login(self.cuenta)
        self.client.post(reverse("perfil_apoderado"), {
            "accion": "guardar_correo", "email": "contacto@example.com",
            "apoderado_id": otro.pk,
        })
        otro.refresh_from_db()
        self.assertEqual(otro.email, "")
