"""Preparación de cuentas y atomicidad de las resoluciones."""
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .models import (Apoderado, ApoderadoJugador, Auditoria,
                     Categoria, Jugador, SolicitudInscripcion, Usuario)
from .services import aprobar_solicitud_inscripcion, marcar_solicitud_en_revision
from .validators import ERROR_IDENTIDAD_INSCRIPCION

TEMPORADA = 2026

class PreparacionCuentasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        cls.administracion = Usuario.objects.create_user(
            rut="20347119-K", password="ClaveAdministrativa123!",
        )

        cls.administracion.groups.add(Group.objects.get_or_create(name="Administración")[0])

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

    def aprobar(self, solicitud):
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        return aprobar_solicitud_inscripcion(
            solicitud=solicitud, usuario=self.administracion,
        )

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

    def test_menor_sin_apoderado_principal_no_se_aprueba(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="", principal=False)
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_menor_sin_correo_del_apoderado_no_se_aprueba(self):
        solicitud = self.solicitud(
            nacimiento=date(2013, 3, 10), email="", correo_apoderado="",
        )
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado)

    def test_conflicto_de_correo_o_rut_vinculado_detiene_aprobacion(self):
        solicitud = self.solicitud()
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="otro@example.com", password="ClaveExistente123!",
        )
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.jugador.usuario_id)
        cuenta.email = "adulto@example.com"
        cuenta.save(update_fields=["email"])
        otro = Jugador(
            rut="22222222-2", usuario=cuenta, nombres="Otro", apellidos="Jugador",
            fecha_nacimiento=date(1990, 3, 10), rama=Jugador.Rama.VARONES,
        )
        Jugador.objects.bulk_create([otro])
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        self.assertEqual(otro.usuario_id, cuenta.pk)

    def test_cuenta_suspendida_no_se_reactiva(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com",
            password="ClaveAnterior123!", is_active=False,
            activado_en=timezone.now(),
        )
        clave = cuenta.password
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        cuenta.refresh_from_db()
        solicitud.refresh_from_db()
        self.assertFalse(cuenta.is_active)
        self.assertEqual(cuenta.password, clave)
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

    def test_cumple_18_durante_espera_y_falta_correo_propio(self):
        hoy = timezone.localdate()
        nacimiento = date(hoy.year - 18, hoy.month, hoy.day) + timedelta(days=1)
        solicitud = self.solicitud(nacimiento=nacimiento, email="")
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with patch("usuarios.services.timezone.localdate", return_value=hoy + timedelta(days=1)):
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_error_tardio_revierte_todos_los_cambios(self):
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Fallo de auditoría")):
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
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
        self.assertFalse(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").exists())

    def test_error_tardio_revierte_vinculo_del_apoderado(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="")
        apoderado = solicitud.jugador.vinculos_apoderados.get().apoderado
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with patch("usuarios.services.registrar_auditoria", side_effect=ValidationError("Fallo")):
            with self.assertRaises(ValidationError):
                aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        apoderado.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado)
        self.assertIsNone(apoderado.usuario)
        self.assertIsNone(solicitud.jugador.usuario)
        self.assertEqual(solicitud.jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_reutiliza_cuenta_adulta_sin_cambiar_credenciales_y_notifica_sin_activacion(self):
        cuenta = Usuario.objects.create_user(
            rut="11111111-1", email="adulto@example.com", password="ClaveExistente123!",
            activado_en=timezone.now(),
        )
        anterior = Usuario.objects.values().get(pk=cuenta.pk)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            aprobada = self.aprobar(self.solicitud())
        self.assertEqual(aprobada.usuario_autorizado_id, cuenta.pk)
        self.assertEqual(Usuario.objects.values().get(pk=cuenta.pk), anterior)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cuenta.email])
        self.assertIn("cuenta habitual", mail.outbox[0].body)
        self.assertNotIn("/activar-cuenta/", mail.outbox[0].body)

    def test_reutiliza_cuenta_pendiente_sin_activarla(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1", email="adulto@example.com", is_active=False)
        aprobada = self.aprobar(self.solicitud())
        cuenta.refresh_from_db()
        self.assertEqual(aprobada.usuario_autorizado_id, cuenta.pk)
        self.assertFalse(cuenta.is_active)
        self.assertFalse(cuenta.has_usable_password())
        self.assertIsNone(cuenta.activado_en)

    def test_menor_reutiliza_cuenta_del_apoderado_sin_reactivacion(self):
        cuenta = Usuario.objects.create_user(
            rut="12345678-5", email="responsable@example.com", password="ClaveExistente123!",
        )
        apoderado = Apoderado.objects.create(
            rut=cuenta.rut, usuario=cuenta, nombres="Patricia", apellidos="Responsable",
            email=cuenta.email, telefono="+56911111111",
        )
        clave = cuenta.password
        aprobada = self.aprobar(self.solicitud(nacimiento=date(2013, 3, 10), email="", apoderado=apoderado))
        cuenta.refresh_from_db()
        self.assertEqual(aprobada.usuario_autorizado_id, cuenta.pk)
        self.assertIsNone(aprobada.jugador.usuario_id)
        self.assertTrue(cuenta.is_active)
        self.assertEqual(cuenta.password, clave)

    def test_identidad_manipulada_del_jugador_no_se_autoriza(self):
        solicitud = self.solicitud()
        otra_cuenta = Usuario.objects.create_user(rut="22222222-2", email="adulto@example.com")
        Jugador.objects.filter(pk=solicitud.jugador_id).update(usuario=otra_cuenta)
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado_id)
        self.assertEqual(Usuario.objects.count(), 2)
        self.assertFalse(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").exists())

    def test_cruce_historico_del_apoderado_impide_aprobar_al_menor(self):
        solicitud = self.solicitud(nacimiento=date(2013, 3, 10), email="")
        apoderado = solicitud.jugador.vinculos_apoderados.get().apoderado
        Jugador.objects.bulk_create([Jugador(
            rut=apoderado.rut, nombres=apoderado.nombres, apellidos=apoderado.apellidos,
            email=apoderado.email, fecha_nacimiento=date(1990, 3, 10), rama="VARONES",
        )])
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
        solicitud.refresh_from_db()
        apoderado.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado_id)
        self.assertIsNone(apoderado.usuario_id)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_aprobacion_desactualizada_no_duplica_cuenta_ni_auditoria(self):
        solicitud = self.solicitud()
        vieja = SolicitudInscripcion.objects.get(pk=solicitud.pk)
        aprobada = self.aprobar(solicitud)
        anterior = SolicitudInscripcion.objects.values().get(pk=solicitud.pk)
        with self.assertRaises(ValidationError):
            aprobar_solicitud_inscripcion(solicitud=vieja, usuario=self.administracion)
        self.assertEqual(SolicitudInscripcion.objects.values().get(pk=solicitud.pk), anterior)
        self.assertEqual(Usuario.objects.count(), 2)
        self.assertEqual(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").count(), 1)
        self.assertEqual(aprobada.usuario_autorizado_id, anterior["usuario_autorizado_id"])

    def test_rollback_externo_descarta_aprobacion_cuenta_y_vinculo(self):
        solicitud = self.solicitud()
        marcar_solicitud_en_revision(solicitud=solicitud, usuario=self.administracion)
        with transaction.atomic():
            aprobar_solicitud_inscripcion(solicitud=solicitud, usuario=self.administracion)
            transaction.set_rollback(True)
        solicitud.refresh_from_db()
        solicitud.jugador.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)
        self.assertIsNone(solicitud.usuario_autorizado_id)
        self.assertIsNone(solicitud.jugador.usuario_id)
        self.assertEqual(Usuario.objects.count(), 1)
        self.assertFalse(Auditoria.objects.filter(accion="SOLICITUD_APROBADA").exists())

    def test_admin_tecnico_no_resuelve_ni_elimina_solicitudes(self):
        from django.contrib import admin
        solicitud = self.solicitud()
        modelo_admin = admin.site._registry[SolicitudInscripcion]
        peticion = RequestFactory().get("/admin/")
        peticion.user = self.administracion
        campos = modelo_admin.get_readonly_fields(peticion, solicitud)
        for campo in ("estado", "usuario_autorizado", "revisado_por", "fecha_revision", "motivo_rechazo", "jugador"):
            self.assertIn(campo, campos)
        self.assertFalse(modelo_admin.has_add_permission(peticion))
        self.assertFalse(modelo_admin.has_delete_permission(peticion, solicitud))
        self.assertNotIn("delete_selected", modelo_admin.get_actions(peticion))
