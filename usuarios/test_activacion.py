import re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib import admin
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import InscripcionJugadorForm
from .models import AlertaSalud, Apoderado, ApoderadoJugador, Auditoria, Categoria, Jugador, SolicitudInscripcion, Usuario
from .services import aprobar_solicitud_inscripcion, marcar_solicitud_en_revision
from .tokens import activacion_token_generator


@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
class ActivacionCuentasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        cls.staff = Usuario.objects.create_superuser(
            rut="20347119-K", password="ClaveAdministrativa123!",
        )

    def setUp(self):
        cache.clear()

    def solicitud(self, *, rut="11111111-1", nacimiento=date(1990, 3, 10),
                  email="adulto@example.com", apoderado=None, principal=True,
                  correo_apoderado="responsable@example.com"):
        jugador = Jugador.objects.create(
            rut=rut, nombres="Alex", apellidos="Deportista",
            fecha_nacimiento=nacimiento, rama=Jugador.Rama.VARONES,
            email=email, categoria_actual=Categoria.objects.get(nombre="T/C Varones"),
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
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        return aprobar_solicitud_inscripcion(
            solicitud=solicitud, usuario=self.staff,
            request=request or RequestFactory().get("/"),
        )

    def formulario(self, nacimiento, **cambios):
        datos = {
            "rut": "11111111-1", "nombres": "Alex", "apellidos": "Deportista",
            "fecha_nacimiento": nacimiento.isoformat(), "rama": Jugador.Rama.VARONES,
            "telefono": "+56911111111", "email": "adulto@example.com",
            "nombre_contacto_emergencia": "Contacto", "telefono_contacto_emergencia": "+56922222222",
            "procedencia": Jugador.Procedencia.INDEPENDIENTE,
            "tiene_alerta_salud": "NO", "consentimiento": "on",
            "rut_apoderado": "12345678-5", "nombres_apoderado": "Patricia",
            "apellidos_apoderado": "Responsable", "telefono_apoderado": "+56933333333",
            "email_apoderado": "responsable@example.com", "parentesco": "MADRE",
        }
        datos.update(cambios)
        return InscripcionJugadorForm(datos)

    def enlace_aprobacion(self, solicitud):
        with self.captureOnCommitCallbacks(execute=True):
            aprobada = self.aprobar(solicitud)
        enlace = re.search(r"https?://\S+", mail.outbox[-1].body).group(0)
        return aprobada.usuario_autorizado, urlparse(enlace).path

    def test_adulto_exige_correo_y_limite_exacto_de_18(self):
        hoy = timezone.localdate()
        cumple_18 = date(hoy.year - 18, hoy.month, hoy.day)
        adulto = self.formulario(cumple_18, email="")
        self.assertFalse(adulto.is_valid())
        self.assertIn("email", adulto.errors)
        menor = self.formulario(cumple_18 + timedelta(days=1), email="")
        self.assertTrue(menor.is_valid())

    def test_menor_exige_correo_del_apoderado_pero_no_propio(self):
        nacimiento = date(2013, 3, 10)
        sin_apoderado = self.formulario(nacimiento, email="", email_apoderado="")
        self.assertFalse(sin_apoderado.is_valid())
        self.assertIn("email_apoderado", sin_apoderado.errors)
        valido = self.formulario(nacimiento, email="")
        self.assertTrue(valido.is_valid())

    def test_pendiente_y_en_revision_no_crean_usuario(self):
        solicitud = self.solicitud()
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertIsNone(solicitud.jugador.usuario)
        self.assertEqual(Usuario.objects.count(), 1)
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_aprobacion_adulta_crea_cuenta_inactiva_y_autorizada(self):
        solicitud = self.solicitud()
        aprobada = self.aprobar(solicitud)
        cuenta = aprobada.usuario_autorizado
        self.assertEqual(aprobada.estado, SolicitudInscripcion.Estado.APROBADA)
        self.assertEqual(aprobada.jugador.usuario_id, cuenta.pk)
        self.assertEqual(cuenta.email, "adulto@example.com")
        self.assertFalse(cuenta.is_active)
        self.assertFalse(cuenta.has_usable_password())
        self.assertIsNone(cuenta.activado_en)

    def test_aprobacion_menor_autoriza_apoderado_sin_cuenta_juvenil(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="")
        aprobada = self.aprobar(solicitud)
        apoderado = aprobada.jugador.vinculos_apoderados.get().apoderado
        self.assertEqual(apoderado.usuario_id, aprobada.usuario_autorizado_id)
        self.assertEqual(apoderado.usuario.email, "responsable@example.com")
        self.assertIsNone(aprobada.jugador.usuario_id)

    def test_aprobacion_en_cumpleanos_18_autoriza_al_jugador(self):
        hoy = timezone.localdate()
        solicitud = self.solicitud(
            nacimiento=date(hoy.year - 18, hoy.month, hoy.day),
        )
        aprobada = self.aprobar(solicitud)
        self.assertEqual(aprobada.usuario_autorizado.rut, solicitud.jugador.rut)
        self.assertEqual(aprobada.jugador.usuario_id, aprobada.usuario_autorizado_id)

    def test_reutiliza_cuenta_adulta_sin_modificar_credenciales(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com", password="ClaveExistente123!",
            activado_en=timezone.now(),
        )
        clave = cuenta.password
        solicitud = self.solicitud()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aprobada = self.aprobar(solicitud)
            self.assertEqual(len(mail.outbox), 0)
        cuenta.refresh_from_db()
        self.assertEqual(aprobada.usuario_autorizado_id, cuenta.pk)
        self.assertEqual(cuenta.password, clave)
        self.assertTrue(cuenta.is_active)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["adulto@example.com"])
        self.assertIn("cuenta habitual", mail.outbox[0].body)
        self.assertNotIn("/activar-cuenta/", mail.outbox[0].body)

    def test_apoderado_activado_inscribe_otro_jugador_sin_reactivacion(self):
        cuenta = Usuario.objects.create_user(
            rut="12345678-5", email="responsable@example.com",
            password="ClaveExistente123!", activado_en=timezone.now(),
        )
        apoderado = Apoderado.objects.create(
            usuario=cuenta, rut=cuenta.rut, nombres="Patricia", apellidos="Responsable",
            telefono="+56911111111", email=cuenta.email,
        )
        clave = cuenta.password
        self.client.force_login(cuenta)
        datos = self.formulario(date(2013, 3, 10), rut="22222222-2", email="").data.copy()
        for campo in ("rut_apoderado", "nombres_apoderado", "apellidos_apoderado", "telefono_apoderado", "email_apoderado"):
            datos.pop(campo, None)
        respuesta = self.client.post(reverse("agregar_jugador_apoderado"), datos)
        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        solicitud = SolicitudInscripcion.objects.get(jugador__rut="22222222-2")
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aprobada = self.aprobar(solicitud)
        cuenta.refresh_from_db()
        self.assertEqual(aprobada.usuario_autorizado_id, cuenta.pk)
        self.assertEqual(apoderado.usuario_id, cuenta.pk)
        self.assertEqual(cuenta.password, clave)
        self.assertTrue(cuenta.is_active)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["responsable@example.com"])
        self.assertIn("cuenta habitual", mail.outbox[0].body)
        self.assertNotIn("/activar-cuenta/", mail.outbox[0].body)

    def test_menor_sin_apoderado_principal_no_se_aprueba(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="", principal=False)
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_menor_sin_correo_del_apoderado_no_se_aprueba(self):
        solicitud = self.solicitud(
            nacimiento=date(2013, 3, 10), email="", correo_apoderado="",
        )
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado)

    def test_conflicto_de_correo_o_rut_vinculado_detiene_aprobacion(self):
        solicitud = self.solicitud()
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="otro@example.com", password="ClaveExistente123!",
        )
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.jugador.usuario_id)
        cuenta.email = "adulto@example.com"
        cuenta.save(update_fields=["email"])
        otro = Jugador.objects.create(
            rut="22222222-2", usuario=cuenta, nombres="Otro", apellidos="Jugador",
            fecha_nacimiento=date(1990, 3, 10), rama=Jugador.Rama.VARONES,
        )
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        self.assertEqual(otro.usuario_id, cuenta.pk)

    def test_cuenta_suspendida_no_se_reactiva(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com",
            password="ClaveAnterior123!", is_active=False,
            activado_en=timezone.now(),
        )
        clave = cuenta.password
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        cuenta.refresh_from_db()
        solicitud.refresh_from_db()
        self.assertFalse(cuenta.is_active)
        self.assertEqual(cuenta.password, clave)
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

    def test_cumple_18_durante_espera_y_falta_correo_propio(self):
        hoy = timezone.localdate()
        nacimiento = date(hoy.year - 18, hoy.month, hoy.day) + timedelta(days=1)
        solicitud = self.solicitud(nacimiento=nacimiento, email="")
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with patch("usuarios.services.timezone.localdate", return_value=hoy + timedelta(days=1)):
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_error_tardio_revierte_todos_los_cambios(self):
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Fallo de auditoría")):
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.revisado_por)
        self.assertIsNone(solicitud.fecha_revision)
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertIsNone(solicitud.jugador.usuario)
        self.assertEqual(solicitud.jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertIsNone(solicitud.jugador.fecha_ingreso)
        self.assertEqual(Usuario.objects.count(), 1)
        self.assertFalse(Auditoria.objects.exists())

    def test_error_tardio_revierte_vinculo_del_apoderado(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="")
        apoderado = solicitud.jugador.vinculos_apoderados.get().apoderado
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Fallo")):
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        apoderado.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertIsNone(apoderado.usuario)
        self.assertIsNone(solicitud.jugador.usuario)
        self.assertEqual(solicitud.jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(Usuario.objects.count(), 1)

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
                marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
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
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.staff)
        vieja = SolicitudInscripcion.objects.get(pk=solicitud.pk)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
            anterior = SolicitudInscripcion.objects.values().get(pk=solicitud.pk)
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=vieja, usuario=self.staff)
            self.assertEqual(SolicitudInscripcion.objects.values().get(pk=solicitud.pk), anterior)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cuenta.email])
        self.assertEqual(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").count(), 1)

    def test_admin_no_expone_transiciones_sensibles(self):
        solicitud = self.solicitud()
        jugador_admin = admin.site._registry[Jugador]
        solicitud_admin = admin.site._registry[SolicitudInscripcion]
        usuario_admin = admin.site._registry[Usuario]
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.staff
        self.assertIn("estado", jugador_admin.get_readonly_fields(peticion, solicitud.jugador))
        self.assertIn("usuario", jugador_admin.get_readonly_fields(peticion, solicitud.jugador))
        self.assertIn("estado", solicitud_admin.get_readonly_fields(peticion, solicitud))
        self.assertIn("usuario_autorizado", solicitud_admin.get_readonly_fields(peticion, solicitud))
        cuenta = Usuario.objects.create_user(rut="33333333-3", email="otro@example.com")
        self.assertIn("is_active", usuario_admin.get_readonly_fields(peticion, cuenta))
        formulario_usuario = usuario_admin.get_form(peticion)
        formulario_admin = formulario_usuario({
            "rut": "22222222-2", "email": "nuevo@example.com", "is_staff": False,
            "password1": "ClavePropiaMuySegura123!", "password2": "ClavePropiaMuySegura123!",
        })
        self.assertFalse(formulario_admin.is_valid())
        formulario_personal = formulario_usuario({
            "rut": "22222222-2", "email": "nuevo@example.com", "is_staff": True,
            "is_active": True,
            "password1": "ClavePropiaMuySegura123!", "password2": "ClavePropiaMuySegura123!",
        })
        self.assertTrue(formulario_personal.is_valid(), formulario_personal.errors)
