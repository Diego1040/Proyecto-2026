from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from institucional import services
from institucional.models import DocumentoNormativo, VersionDocumentoNormativo
from usuarios.models import Auditoria

from .base import BaseInstitucionalTest, pdf


class NormativaTest(BaseInstitucionalTest):
    def crear(self, archivo=True):
        return services.crear_documento(usuario=self.admin, codigo="REG-01", tipo="REGLAMENTO", datos=self.datos_documento(), archivo=pdf() if archivo else None)

    def test_administracion_sin_staff_crea_borrador_desde_formulario(self):
        self.client.force_login(self.admin)
        datos = self.datos_documento()
        datos.update(codigo="REG-01", tipo="REGLAMENTO", archivo=pdf())
        respuesta = self.client.post(reverse("institucional:documento_nuevo"), datos)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(VersionDocumentoNormativo.objects.get().estado, "BORRADOR")
        self.assertFalse(self.admin.is_staff)

    def test_borrador_oculto_a_miembro_incluso_descarga_directa(self):
        version = self.crear()
        self.client.force_login(self.miembro)
        self.assertNotContains(self.client.get(reverse("institucional:documentos")), version.titulo)
        for nombre, pk in (("documento_detalle", version.documento_id), ("documento_descargar", version.pk)):
            self.assertEqual(self.client.get(reverse(f"institucional:{nombre}", args=[pk])).status_code, 404)

    def test_publica_y_muestra_fecha_version_vigencia_y_descarga_privada(self):
        version = self.crear()
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        self.client.force_login(self.miembro)
        respuesta = self.client.get(reverse("institucional:documento_detalle", args=[version.documento_id]))
        for texto in ("Reglamento del club", "1.0", "Vigente", timezone.localdate().strftime("%d/%m/%Y")):
            self.assertContains(respuesta, texto)
        descarga = self.client.get(reverse("institucional:documento_descargar", args=[version.pk]))
        self.assertEqual(descarga.status_code, 200)
        self.assertTrue(b"".join(descarga.streaming_content).startswith(b"%PDF-"))
        self.assertIn("attachment", descarga["Content-Disposition"])
        self.assertIn("no-store", descarga["Cache-Control"])
        self.assertEqual(descarga["X-Content-Type-Options"], "nosniff")

    def test_segunda_publicacion_conserva_primera_y_una_sola_vigente(self):
        primera = self.crear()
        services.publicar_documento(usuario=self.admin, version_id=primera.pk)
        with primera.archivo.open("rb") as archivo:
            contenido = archivo.read()
        segunda = services.nueva_version_documento(usuario=self.admin, documento_id=primera.documento_id, datos=self.datos_documento(version="2.0", motivo_cambio="Actualización aprobada"), archivo=pdf())
        services.publicar_documento(usuario=self.admin, version_id=segunda.pk)
        primera.refresh_from_db()
        self.assertEqual(primera.estado, "HISTORICA")
        with primera.archivo.open("rb") as archivo:
            self.assertEqual(archivo.read(), contenido)
        self.assertEqual(VersionDocumentoNormativo.objects.filter(estado="VIGENTE").count(), 1)
        self.assertTrue(Auditoria.objects.filter(accion="NORMATIVA_VIGENCIA_FINALIZADA", entidad_id=primera.pk).exists())
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[primera.pk])).status_code, 404)
        self.client.force_login(self.admin)
        descarga = self.client.get(reverse("institucional:documento_descargar", args=[primera.pk]))
        self.assertEqual(descarga.status_code, 200)
        descarga.close()

    def test_publicada_no_se_edita_ni_se_borra(self):
        version = self.crear()
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        with self.assertRaises(ValidationError):
            services.editar_documento(usuario=self.admin, version_id=version.pk, datos=self.datos_documento(titulo="Otro"))
        version.titulo = "Otro"
        with self.assertRaises(ValidationError):
            version.save()
        with self.assertRaises(ValidationError):
            version.delete()

    def test_pdf_obligatorio_y_publicacion_futura_rechazada(self):
        version = self.crear(archivo=False)
        with self.assertRaises(ValidationError):
            services.publicar_documento(usuario=self.admin, version_id=version.pk)
        services.editar_documento(usuario=self.admin, version_id=version.pk, datos=self.datos_documento(vigente_desde=timezone.localdate() + timedelta(days=1)), archivo=pdf())
        with self.assertRaises(ValidationError):
            services.publicar_documento(usuario=self.admin, version_id=version.pk)

    def test_modificar_borrador_auditado_y_sin_duplicar_al_republicar(self):
        version = self.crear()
        services.editar_documento(usuario=self.admin, version_id=version.pk, datos=self.datos_documento(titulo="Texto revisado"))
        registro = Auditoria.objects.get(accion="NORMATIVA_BORRADOR_MODIFICADO")
        self.assertEqual(registro.detalle["antes"]["titulo"], "Reglamento del club")
        self.assertEqual(registro.detalle["despues"]["titulo"], "Texto revisado")
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        with self.assertRaises(ValidationError):
            services.publicar_documento(usuario=self.admin, version_id=version.pk)
        self.assertEqual(Auditoria.objects.filter(accion="NORMATIVA_PUBLICADA").count(), 1)

    def test_roles_y_superusuario_sin_grupo_no_gestionan(self):
        for usuario in (self.secretaria, self.comite, self.miembro, self.ajeno):
            with self.subTest(usuario=usuario.pk):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(reverse("institucional:documento_nuevo")).status_code, 403)
                with self.assertRaises(PermissionDenied):
                    services.crear_documento(usuario=usuario, codigo="X", tipo="REGLAMENTO", datos=self.datos_documento())
        self.ajeno.is_staff = self.ajeno.is_superuser = True
        self.ajeno.save()
        self.client.force_login(self.ajeno)
        self.assertEqual(self.client.get(reverse("institucional:documentos")).status_code, 200)
        self.assertEqual(self.client.get(reverse("institucional:documento_nuevo")).status_code, 403)

    def test_anonimo_inactivo_y_grupo_retirado(self):
        self.assertEqual(self.client.get(reverse("institucional:documentos")).status_code, 200)
        self.miembro.is_active = False
        self.miembro.save()
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.get(reverse("institucional:documentos")).status_code, 200)
        self.client.force_login(self.admin)
        self.admin.groups.clear()
        self.assertEqual(self.client.get(reverse("institucional:documento_nuevo")).status_code, 403)

    def test_publicar_solo_post_y_con_csrf(self):
        version = self.crear()
        self.client.force_login(self.admin)
        url = reverse("institucional:documento_publicar", args=[version.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(url).status_code, 403)

    def test_error_auditoria_revierte_bd_y_archivo_nuevo(self):
        with patch("institucional.services.registrar_auditoria", side_effect=RuntimeError("Fallo")):
            with self.assertRaises(RuntimeError):
                self.crear()
        self.assertFalse(DocumentoNormativo.objects.exists())
        self.assertFalse(VersionDocumentoNormativo.objects.exists())
        self.assertEqual(list(self.raiz.rglob("*.pdf")), [])

    def test_nueva_version_exige_justificacion_y_no_admite_dos_borradores(self):
        version = self.crear()
        with self.assertRaises(ValidationError):
            services.nueva_version_documento(usuario=self.admin, documento_id=version.documento_id, datos=self.datos_documento(version="2"))
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        with self.assertRaises(ValidationError):
            services.nueva_version_documento(usuario=self.admin, documento_id=version.documento_id, datos=self.datos_documento(version="2"))

    def test_restriccion_de_base_impide_dos_versiones_vigentes(self):
        version = self.crear()
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VersionDocumentoNormativo.objects.create(documento=version.documento, numero=2, version="2", titulo="Otro", fecha_documento=version.fecha_documento, vigente_desde=version.vigente_desde, estado="VIGENTE", creada_por=self.admin, publicado_por=self.admin, publicado_en=timezone.now())

    def test_archivo_perdido_impide_publicar_y_archivo_alterado_no_se_descarga(self):
        version = self.crear()
        version.archivo.storage.delete(version.archivo.name)
        with self.assertRaises(ValidationError):
            services.publicar_documento(usuario=self.admin, version_id=version.pk)
        services.editar_documento(usuario=self.admin, version_id=version.pk, datos=self.datos_documento(), archivo=pdf())
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        version.refresh_from_db()
        with version.archivo.storage.open(version.archivo.name, "wb") as archivo:
            # Sigue siendo un PDF válido; la huella detecta el cambio de bytes.
            archivo.write(pdf().read() + b"\n% modificado fuera de la aplicacion\n")
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[version.pk])).status_code, 404)
