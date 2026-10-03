"""Regresiones de integridad de identidad del Bloque 15, Etapa 1."""
from datetime import date

from django.contrib import admin
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .forms import InscripcionJugadorForm, SolicitudActivacionForm, UsuarioChangeForm
from .models import Apoderado, ApoderadoJugador, Auditoria, Categoria, Jugador, SolicitudInscripcion, Usuario
from .services import aprobar_solicitud_inscripcion, crear_solicitud_inscripcion, solicitar_activacion
from .validators import ERROR_IDENTIDAD_INSCRIPCION, normalizar_rut, validar_rut


@override_settings(MAILERS={"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}})
class IntegridadIdentidadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        cls.staff = Usuario.objects.create_superuser(
            rut="20347119-K", password="ClaveAdministrativa123!",
        )

    def jugador(self, **cambios):
        datos = {
            "rut": "11111111-1", "nombres": "Alex", "apellidos": "Deportista",
            "email": "titular@example.com", "fecha_nacimiento": date(1990, 3, 10),
            "rama": Jugador.Rama.VARONES,
            "categoria_actual": Categoria.objects.get(nombre="T/C Varones"),
        }
        datos.update(cambios)
        return Jugador(**datos)

    def apoderado(self, **cambios):
        datos = {
            "rut": "11111111-1", "nombres": "Alex", "apellidos": "Deportista",
            "email": "titular@example.com", "telefono": "+56911111111",
        }
        datos.update(cambios)
        return Apoderado(**datos)

    def datos_formulario(self, **cambios):
        datos = {
            "rut": "11111111-1", "nombres": "Alex", "apellidos": "Deportista",
            "email": "titular@example.com", "fecha_nacimiento": "1990-03-10",
            "rama": "VARONES", "telefono": "+56911111111",
            "nombre_contacto_emergencia": "Contacto",
            "telefono_contacto_emergencia": "+56922222222",
            "procedencia": "INDEPENDIENTE", "tiene_alerta_salud": "NO",
            "consentimiento": "on", "rut_apoderado": "12345678-5",
            "nombres_apoderado": "Patricia", "apellidos_apoderado": "Responsable",
            "email_apoderado": "responsable@example.com",
            "telefono_apoderado": "+56933333333", "parentesco": "MADRE",
        }
        datos.update(cambios)
        return datos

    def solicitud(self, jugador):
        return SolicitudInscripcion.objects.create(
            jugador=jugador, estado=SolicitudInscripcion.Estado.EN_REVISION,
            procedencia="INDEPENDIENTE", consentimiento=True,
        )

    def assert_aprobacion_bloqueada(self, solicitud):
        usuarios_antes = Usuario.objects.count()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado_id)
        self.assertIsNone(solicitud.revisado_por_id)
        self.assertIsNone(solicitud.fecha_revision)
        self.assertEqual(solicitud.jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(Usuario.objects.count(), usuarios_antes)
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_cruce_sin_cuenta_se_bloquea_en_ambas_direcciones(self):
        for primero, segundo in ((self.jugador, self.apoderado), (self.apoderado, self.jugador)):
            with self.subTest(primero=primero.__name__):
                with transaction.atomic():
                    primero().save()
                    perfil = segundo()
                    with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
                        perfil.full_clean()
                    with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
                        perfil.save()
                    transaction.set_rollback(True)

    def test_mismos_nombres_y_correo_no_autorizan_reutilizacion_transversal(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="titular@example.com", password="ClaveExistente123!",
        )
        self.apoderado(usuario=cuenta).save()
        # Simula datos previos/importados que el nuevo save ya no permite crear.
        jugador = self.jugador()
        Jugador.objects.bulk_create([jugador])
        self.assert_aprobacion_bloqueada(self.solicitud(jugador))
        cuenta.refresh_from_db()
        self.assertTrue(cuenta.is_active)
        self.assertEqual(cuenta.email, "titular@example.com")
        jugador.refresh_from_db()
        self.assertIsNone(jugador.usuario_id)

    def test_colision_del_apoderado_detiene_aprobacion_del_menor(self):
        self.jugador().save()
        apoderado = self.apoderado()
        Apoderado.objects.bulk_create([apoderado])
        menor = self.jugador(rut="22222222-2", fecha_nacimiento=date(2013, 3, 10), email="")
        menor.save()
        ApoderadoJugador.objects.create(
            jugador=menor, apoderado=apoderado, parentesco="MADRE", es_principal=True,
        )
        self.assert_aprobacion_bloqueada(self.solicitud(menor))
        apoderado.refresh_from_db()
        self.assertIsNone(apoderado.usuario_id)

    def test_servicio_de_creacion_rechaza_cruce_sin_guardar_jugador(self):
        self.apoderado().save()
        with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
            crear_solicitud_inscripcion(jugador=self.jugador(), consentimiento=True)
        self.assertFalse(Jugador.objects.exists())
        self.assertFalse(SolicitudInscripcion.objects.exists())

    def test_publica_bloquea_ambos_cruces_con_mensaje_generico_y_sin_datos(self):
        escenarios = (
            (self.apoderado(nombres="NombreReservado", apellidos="ApellidoReservado"), {}),
            (self.jugador(rut="12345678-5", nombres="NombreReservado", apellidos="ApellidoReservado"),
             {"fecha_nacimiento": "2013-03-10", "email": ""}),
        )
        for existente, cambios in escenarios:
            with self.subTest(modelo=type(existente).__name__):
                with transaction.atomic():
                    existente.save()
                    cantidades = (Jugador.objects.count(), Apoderado.objects.count(), Usuario.objects.count())
                    respuesta = self.client.post(reverse("inscripcion"), self.datos_formulario(**cambios))
                    self.assertEqual(respuesta.status_code, 200)
                    self.assertContains(respuesta, ERROR_IDENTIDAD_INSCRIPCION)
                    self.assertNotContains(respuesta, "NombreReservado")
                    self.assertNotContains(respuesta, "ApellidoReservado")
                    self.assertEqual(cantidades, (Jugador.objects.count(), Apoderado.objects.count(), Usuario.objects.count()))
                    self.assertFalse(SolicitudInscripcion.objects.exists())
                    transaction.set_rollback(True)

    def test_apoderado_autenticado_no_crea_automaticamente_su_segundo_perfil(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1", password="ClaveExistente123!")
        self.apoderado(usuario=cuenta).save()
        self.client.force_login(cuenta)
        respuesta = self.client.post(reverse("agregar_jugador_apoderado"), self.datos_formulario())
        self.assertContains(respuesta, ERROR_IDENTIDAD_INSCRIPCION)
        self.assertFalse(Jugador.objects.exists())
        self.assertFalse(SolicitudInscripcion.objects.exists())

    def test_doble_perfil_adulto_explicitamente_vinculado_se_conserva(self):
        for primero, segundo in ((self.apoderado, self.jugador), (self.jugador, self.apoderado)):
            with self.subTest(primero=primero.__name__):
                with transaction.atomic():
                    cuenta = Usuario.objects.create_user(
                        rut="11111111-1", email="titular@example.com", password="ClaveExistente123!",
                    )
                    perfil = primero(usuario=cuenta)
                    perfil.save()
                    otro = segundo(usuario=cuenta)
                    otro.full_clean()
                    otro.save()
                    jugador = perfil if isinstance(perfil, Jugador) else otro
                    solicitud = crear_solicitud_inscripcion(jugador=jugador, consentimiento=True)
                    solicitud.estado = SolicitudInscripcion.Estado.EN_REVISION
                    solicitud.save(update_fields=["estado"])
                    aprobada = aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.staff)
                    self.assertEqual(aprobada.usuario_autorizado_id, cuenta.pk)
                    self.assertEqual(cuenta.jugador.usuario_id, cuenta.apoderado.usuario_id)
                    transaction.set_rollback(True)

    def test_vinculo_incompleto_o_cuenta_de_otro_rut_no_habilita_cruce(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        otra = Usuario.objects.create_user(rut="22222222-2")
        self.apoderado().save()
        for usuario in (cuenta, otra):
            with self.subTest(usuario=usuario.pk):
                with self.assertRaises(ValidationError):
                    self.jugador(usuario=usuario).save()
        Apoderado.objects.filter(rut=cuenta.rut).update(usuario=otra)
        with self.assertRaises(ValidationError):
            self.jugador(usuario=otra).save()

    def test_menor_no_puede_tener_doble_perfil_ni_con_cuenta_compartida(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        self.apoderado(usuario=cuenta).save()
        with self.assertRaises(ValidationError):
            self.jugador(usuario=cuenta, fecha_nacimiento=date(2013, 3, 10)).save()

    def test_formulario_menor_rechaza_autorepresentacion_nueva_y_existente(self):
        datos = self.datos_formulario(fecha_nacimiento="2013-03-10", email="", rut_apoderado="011111111-1")
        self.assertFalse(InscripcionJugadorForm(datos).is_valid())
        apoderado = self.apoderado()
        apoderado.save()
        formulario = InscripcionJugadorForm(datos, apoderado_existente=apoderado)
        self.assertFalse(formulario.is_valid())
        self.assertIn(ERROR_IDENTIDAD_INSCRIPCION, str(formulario.errors))

    def test_relacion_menor_consigo_mismo_se_rechaza_en_clean_y_save(self):
        menor = self.jugador(fecha_nacimiento=date(2013, 3, 10))
        menor.save()
        apoderado = self.apoderado()
        Apoderado.objects.bulk_create([apoderado])
        for activo in (True, False):
            vinculo = ApoderadoJugador(jugador=menor, apoderado=apoderado, parentesco="TUTOR", activo=activo)
            with self.subTest(activo=activo):
                with self.assertRaises(ValidationError):
                    vinculo.full_clean()
                with self.assertRaises(ValidationError):
                    vinculo.save()
        self.assertFalse(ApoderadoJugador.objects.exists())

    def test_servicios_rechazan_autorepresentacion_preexistente(self):
        menor = self.jugador(fecha_nacimiento=date(2013, 3, 10))
        menor.save()
        apoderado = self.apoderado()
        Apoderado.objects.bulk_create([apoderado])
        ApoderadoJugador.objects.bulk_create([
            ApoderadoJugador(jugador=menor, apoderado=apoderado, parentesco="TUTOR", es_principal=True),
        ])
        with self.assertRaises(ValidationError):
            crear_solicitud_inscripcion(jugador=menor, consentimiento=True)
        self.assert_aprobacion_bloqueada(self.solicitud(menor))

    def test_relacion_menor_con_misma_cuenta_y_ruts_distintos_tambien_se_rechaza(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        menor = self.jugador(usuario=cuenta, rut="22222222-2", fecha_nacimiento=date(2013, 3, 10))
        menor.save()
        apoderado = self.apoderado(usuario=cuenta)
        apoderado.save()
        with self.assertRaises(ValidationError):
            ApoderadoJugador.objects.create(jugador=menor, apoderado=apoderado, parentesco="TUTOR")

    def test_normaliza_ceros_sin_alterar_el_digito_verificador(self):
        for entrada, esperado in (("011111111-1", "11111111-1"), ("01.234.567-4", "1234567-4"),
                                  ("020347119-k", "20347119-K")):
            with self.subTest(entrada=entrada):
                self.assertEqual(normalizar_rut(entrada), esperado)
                validar_rut(entrada)
        with self.assertRaises(ValidationError):
            validar_rut("011111111-2")

    def test_ceros_no_permiten_duplicar_usuario_jugador_ni_apoderado(self):
        for fabrica in (lambda rut: Usuario(rut=rut),
                        lambda rut: self.jugador(rut=rut), lambda rut: self.apoderado(rut=rut)):
            with transaction.atomic():
                perfil = fabrica("011111111-1")
                perfil.save()
                self.assertEqual(perfil.rut, "11111111-1")
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        fabrica("11111111-1").save()
                transaction.set_rollback(True)

    def test_full_clean_canonicaliza_los_tres_modelos(self):
        cuenta = Usuario(rut="011111111-1")
        cuenta.set_unusable_password()
        for perfil in (cuenta, self.jugador(rut="011111111-1"),
                       self.apoderado(rut="011111111-1")):
            with self.subTest(modelo=type(perfil).__name__):
                perfil.full_clean()
                self.assertEqual(perfil.rut, "11111111-1")

    def test_ceros_no_evitan_conflicto_transversal_ni_duplicado_del_formulario(self):
        self.apoderado().save()
        formulario = InscripcionJugadorForm(self.datos_formulario(rut="011111111-1"))
        self.assertFalse(formulario.is_valid())
        self.assertIn(ERROR_IDENTIDAD_INSCRIPCION, str(formulario.errors))
        Apoderado.objects.all().delete()
        self.jugador().save()
        self.assertFalse(InscripcionJugadorForm(self.datos_formulario(rut="011111111-1")).is_valid())

    def test_busqueda_natural_y_login_usan_rut_canonico(self):
        cuenta = Usuario.objects.create_user(rut="011111111-1", password="ClaveExistente123!")
        self.assertEqual(Usuario.objects.get_by_natural_key("011111111-1"), cuenta)
        self.assertEqual(Usuario.objects.get_by_natural_key("11.111.111-1"), cuenta)
        respuesta = self.client.post(reverse("login"), {"username": "011111111-1", "password": "ClaveExistente123!"})
        self.assertRedirects(respuesta, reverse("panel"))

    async def test_busqueda_natural_asincrona_usa_rut_canonico(self):
        cuenta = await Usuario.objects.acreate(rut="011111111-1")
        self.assertEqual(await Usuario.objects.aget_by_natural_key("011111111-1"), cuenta)

    def test_reenvio_de_activacion_busca_rut_canonico(self):
        jugador = self.jugador()
        jugador.save()
        with self.captureOnCommitCallbacks(execute=True):
            aprobada = aprobar_solicitud_inscripcion(
                solicitud=self.solicitud(jugador), usuario=self.staff, request=RequestFactory().get("/"),
            )
        mail.outbox.clear()
        cache.delete(f"activacion-reenvio:{aprobada.usuario_autorizado_id}")
        formulario = SolicitudActivacionForm({"rut": "011111111-1", "email": jugador.email})
        self.assertTrue(formulario.is_valid())
        self.assertEqual(formulario.cleaned_data["rut"], "11111111-1")
        with self.captureOnCommitCallbacks(execute=True):
            solicitar_activacion(rut="011111111-1", correo=jugador.email, request=RequestFactory().get("/"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [aprobada.usuario_autorizado.email])

    def test_cambio_rut_vinculado_se_rechaza_en_clean_save_y_formulario(self):
        for tipo in ("jugador", "apoderado", "ambos"):
            with self.subTest(tipo=tipo):
                with transaction.atomic():
                    cuenta = Usuario.objects.create_user(rut="11111111-1")
                    if tipo in ("jugador", "ambos"):
                        self.jugador(usuario=cuenta).save()
                    if tipo in ("apoderado", "ambos"):
                        self.apoderado(usuario=cuenta).save()
                    cuenta.rut = "33333333-3"
                    with self.assertRaises(ValidationError):
                        cuenta.full_clean()
                    with self.assertRaises(ValidationError):
                        cuenta.save(update_fields=["rut"])
                    cuenta.refresh_from_db()
                    self.assertEqual(cuenta.rut, "11111111-1")
                    formulario = UsuarioChangeForm(
                        {"rut": "33333333-3", "email": "", "is_active": True}, instance=cuenta,
                    )
                    self.assertFalse(formulario.is_valid())
                    cuenta.refresh_from_db()
                    self.assertEqual(cuenta.rut, "11111111-1")
                    transaction.set_rollback(True)

    def test_admin_oculta_rut_vinculado_y_ignora_post_manipulado(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        self.jugador(usuario=cuenta).save()
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.staff
        modelo_admin = admin.site._registry[Usuario]
        self.assertIn("rut", modelo_admin.get_readonly_fields(peticion, cuenta))
        clase_formulario = modelo_admin.get_form(peticion, cuenta)
        self.assertNotIn("rut", clase_formulario.base_fields)
        datos = model_to_dict(cuenta, fields=list(clase_formulario.base_fields))
        datos["rut"] = "33333333-3"
        formulario = clase_formulario(datos, instance=cuenta)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        formulario.save()
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.rut, "11111111-1")

    def test_admin_rut_solo_lectura_para_apoderado_y_ambos(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        self.apoderado(usuario=cuenta).save()
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.staff
        modelo_admin = admin.site._registry[Usuario]
        self.assertIn("rut", modelo_admin.get_readonly_fields(peticion, cuenta))
        self.jugador(usuario=cuenta).save()
        self.assertIn("rut", modelo_admin.get_readonly_fields(peticion, cuenta))

    def test_cuenta_sin_perfil_permite_cambio_y_equivalencia_no_es_cambio_identidad(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.staff
        self.assertNotIn("rut", admin.site._registry[Usuario].get_readonly_fields(peticion, cuenta))
        cuenta.rut = "33333333-3"
        cuenta.full_clean()
        cuenta.save()
        jugador = self.jugador(rut=cuenta.rut, usuario=cuenta)
        jugador.save()
        cuenta.rut = "033333333-3"
        cuenta.full_clean()
        cuenta.save()
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.rut, jugador.rut)

    def test_editar_otro_campo_no_cambia_el_rut_vinculado(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        self.apoderado(usuario=cuenta).save()
        cuenta.email = "contacto@example.com"
        cuenta.save(update_fields=["email", "updated_at"])
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.rut, "11111111-1")
        self.assertEqual(cuenta.email, "contacto@example.com")
