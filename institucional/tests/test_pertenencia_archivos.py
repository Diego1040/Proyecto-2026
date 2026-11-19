from datetime import date
from io import BytesIO, StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from pypdf import PdfWriter

from institucional.permisos import es_miembro_autorizado
from institucional.services import autorizar_miembro
from institucional.storage import almacenamiento_privado
from institucional.validators import validar_pdf
from usuarios.models import Apoderado, ApoderadoJugador, Auditoria, Jugador, PeriodoInactividad, SolicitudInscripcion, Usuario

from .base import BaseInstitucionalTest, pdf, rut


class PertenenciaTest(BaseInstitucionalTest):
    def test_autenticacion_y_activacion_no_acreditan_pertenencia(self):
        self.ajeno.activado_en = timezone.now()
        self.ajeno.save()
        self.assertFalse(es_miembro_autorizado(self.ajeno))

    def test_jugador_aprobado_conserva_acceso_en_inactividad_documentada(self):
        jugador = self.jugador_aprobado()
        self.assertTrue(es_miembro_autorizado(self.ajeno))
        PeriodoInactividad.objects.create(jugador=jugador, motivo="LESION", fecha_inicio=timezone.localdate())
        jugador.refresh_from_db()
        self.assertEqual(jugador.estado, "INACTIVO")
        self.assertTrue(es_miembro_autorizado(self.ajeno))

    def test_inactivo_sin_periodo_no_accede_por_inscripcion(self):
        jugador = self.jugador_aprobado()
        Jugador.objects.filter(pk=jugador.pk).update(estado="INACTIVO")
        self.assertFalse(es_miembro_autorizado(self.ajeno))

    def test_cuenta_pendiente_no_accede_ni_con_grupo_manual(self):
        jugador = self.jugador_aprobado()
        Jugador.objects.filter(pk=jugador.pk).update(estado="PENDIENTE")
        self.ajeno.groups.add(Group.objects.get(name="Miembros autorizados"))
        self.assertFalse(es_miembro_autorizado(self.ajeno))

    def test_apoderado_necesita_vinculo_actual_y_autorizacion_de_esa_cuenta(self):
        apoderado = Apoderado.objects.create(usuario=self.ajeno, rut=self.ajeno.rut, nombres="Responsable", apellidos="Ayllu", telefono="123")
        jugador = Jugador.objects.create(rut=rut(22000001), nombres="Menor", apellidos="Ayllu", fecha_nacimiento=date(2014, 1, 1), rama="VARONES", estado="ACTIVO")
        vinculo = ApoderadoJugador.objects.create(apoderado=apoderado, jugador=jugador, parentesco="Madre", activo=True, puede_gestionar=True)
        solicitud = SolicitudInscripcion.objects.create(jugador=jugador, estado="APROBADA", procedencia="INDEPENDIENTE", consentimiento=True, usuario_autorizado=self.ajeno)
        self.assertTrue(es_miembro_autorizado(self.ajeno))
        PeriodoInactividad.objects.create(jugador=jugador, motivo="RECESO_PERSONAL", fecha_inicio=timezone.localdate())
        self.assertTrue(es_miembro_autorizado(self.ajeno))
        self.ajeno.groups.add(Group.objects.get(name="Miembros autorizados"))
        vinculo.activo = False
        vinculo.save()
        self.assertFalse(es_miembro_autorizado(self.ajeno))
        vinculo.activo, vinculo.puede_gestionar = True, False
        vinculo.save()
        self.assertFalse(es_miembro_autorizado(self.ajeno))

    def test_autorizacion_manual_auditada_revocable_y_atomica(self):
        autorizar_miembro(usuario=self.admin, destinatario=self.ajeno, autorizar=True, motivo="Identidad y pertenencia histórica verificadas")
        self.assertTrue(es_miembro_autorizado(self.ajeno))
        registro = Auditoria.objects.get(accion="MIEMBRO_AUTORIZADO")
        self.assertEqual(registro.usuario, self.admin)
        self.assertEqual(registro.entidad_id, self.ajeno.pk)
        autorizar_miembro(usuario=self.admin, destinatario=self.ajeno, autorizar=False, motivo="Fin de autorización")
        self.assertFalse(es_miembro_autorizado(self.ajeno))
        with patch("institucional.services.registrar_auditoria", side_effect=RuntimeError("Fallo")):
            with self.assertRaises(RuntimeError):
                autorizar_miembro(usuario=self.admin, destinatario=self.ajeno, autorizar=True, motivo="Verificado")
        self.assertFalse(es_miembro_autorizado(self.ajeno))

    def test_configuracion_idempotente_preserva_permisos_y_no_asigna_cuentas(self):
        grupo = Group.objects.get(name="Administración")
        permiso = grupo.permissions.first()
        personas = Usuario.objects.count()
        miembros = list(grupo.user_set.values_list("pk", flat=True))
        for _ in range(2):
            call_command("configurar_institucional", stdout=StringIO())
        self.assertTrue(grupo.permissions.filter(pk=permiso.pk).exists())
        self.assertEqual(Usuario.objects.count(), personas)
        self.assertEqual(list(grupo.user_set.values_list("pk", flat=True)), miembros)


class ArchivosTest(BaseInstitucionalTest):
    def test_pdf_valido_y_almacenamiento_sin_url_publica(self):
        archivo = pdf()
        self.assertEqual(len(validar_pdf(archivo)["sha256"]), 64)
        with self.assertRaises(NotImplementedError):
            almacenamiento_privado().url("normativa/" + "a" * 32 + ".pdf")

    def test_pdf_vacio_corrupto_falso_y_extension_invalida(self):
        for nombre, contenido in (("x.pdf", b""), ("x.pdf", b"%PDF-1.7\ncorrupto"), ("x.pdf", b"<html>falso</html>"), ("x.html", b"%PDF-1.7")):
            with self.subTest(nombre=nombre, contenido=contenido), self.assertRaises(ValidationError):
                validar_pdf(SimpleUploadedFile(nombre, contenido))

    @override_settings(INSTITUCIONAL_PDF_MAX_BYTES=100)
    def test_limite_tamano(self):
        with self.assertRaises(ValidationError):
            validar_pdf(pdf())

    def test_rechaza_pdf_cifrado_y_javascript(self):
        for accion in ("clave", "javascript"):
            escritor = PdfWriter()
            escritor.add_blank_page(width=100, height=100)
            if accion == "clave":
                escritor.encrypt("secreto")
            else:
                escritor.add_js("app.alert('ejecutar');")
            buffer = BytesIO()
            escritor.write(buffer)
            with self.assertRaises(ValidationError):
                validar_pdf(SimpleUploadedFile("x.pdf", buffer.getvalue()))

    def test_rutas_publicas_y_traversal_rechazados(self):
        with override_settings(INSTITUCIONAL_PRIVATE_ROOT=settings.BASE_DIR):
            with self.assertRaises(ImproperlyConfigured):
                almacenamiento_privado().path("normativa/" + "a" * 32 + ".pdf")
        for nombre in ("../x.pdf", "normativa/../../x.pdf", "C:\\x.pdf", "actas/x.pdf"):
            with self.assertRaises(SuspiciousFileOperation):
                almacenamiento_privado().path(nombre)
