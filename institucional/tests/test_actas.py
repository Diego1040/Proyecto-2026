import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from institucional import services
from institucional.models import Acta, VersionActa
from usuarios.models import Auditoria

from .base import BaseInstitucionalTest, pdf


class ActasTest(BaseInstitucionalTest):
    def datos(self, **cambios):
        datos = {"titulo": "Reunión de octubre", "fecha_reunion": timezone.localdate(), "acuerdos": "Aprobar actividades del club.", "motivo_cambio": ""}
        datos.update(cambios)
        return datos

    def crear(self, archivo=None):
        return services.crear_acta(usuario=self.secretaria, codigo="2026-01", datos=self.datos(), archivo=archivo)

    def test_secretaria_crea_edita_y_publica_sin_pdf(self):
        self.client.force_login(self.secretaria)
        datos = self.datos()
        datos["codigo"] = "2026-01"
        self.assertEqual(self.client.post(reverse("institucional:acta_nueva"), datos).status_code, 302)
        version = VersionActa.objects.get()
        services.editar_acta(usuario=self.secretaria, version_id=version.pk, datos=self.datos(acuerdos="Acuerdo revisado"))
        self.assertEqual(self.client.post(reverse("institucional:acta_publicar", args=[version.pk])).status_code, 302)
        version.refresh_from_db()
        self.assertEqual(version.estado, "PUBLICADA")
        self.assertEqual(version.publicado_por, self.secretaria)
        self.assertFalse(version.archivo)
        registro = Auditoria.objects.get(accion="ACTA_BORRADOR_MODIFICADO")
        self.assertEqual(registro.detalle["campos_modificados"], ["acuerdos"])
        self.assertNotIn("acuerdos", registro.detalle["despues"])

    def test_administracion_y_superusuario_sin_secretaria_no_publican(self):
        version = self.crear()
        self.ajeno.is_staff = self.ajeno.is_superuser = True
        self.ajeno.save()
        for usuario in (self.admin, self.comite, self.miembro, self.ajeno):
            with self.subTest(usuario=usuario.pk):
                self.client.force_login(usuario)
                self.assertEqual(self.client.post(reverse("institucional:acta_publicar", args=[version.pk])).status_code, 403)
                with self.assertRaises(PermissionDenied):
                    services.publicar_acta(usuario=usuario, version_id=version.pk)

    def test_miembro_solo_consulta_publicadas_y_no_historial_de_borrador(self):
        version = self.crear(pdf("acta.pdf"))
        self.client.force_login(self.miembro)
        self.assertNotContains(self.client.get(reverse("institucional:actas")), version.titulo)
        self.assertEqual(self.client.get(reverse("institucional:acta_detalle", args=[version.acta_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("institucional:acta_descargar", args=[version.pk])).status_code, 404)
        services.publicar_acta(usuario=self.secretaria, version_id=version.pk)
        respuesta = self.client.get(reverse("institucional:acta_detalle", args=[version.acta_id]))
        self.assertContains(respuesta, version.acuerdos)
        self.assertNotContains(respuesta, "Historial de gestión")
        descarga = self.client.get(reverse("institucional:acta_descargar", args=[version.pk]))
        self.assertEqual(descarga.status_code, 200)
        self.assertIn("no-store", descarga["Cache-Control"])
        descarga.close()

    def test_correccion_crea_version_y_conserva_texto_y_pdf_originales(self):
        primera = self.crear(pdf("acta.pdf"))
        services.publicar_acta(usuario=self.secretaria, version_id=primera.pk)
        nombre = primera.archivo.name
        segunda = services.nueva_version_acta(usuario=self.secretaria, acta_id=primera.acta_id, datos=self.datos(acuerdos="Acuerdo corregido", motivo_cambio="Se corrigió una transcripción"))
        services.publicar_acta(usuario=self.secretaria, version_id=segunda.pk)
        primera.refresh_from_db()
        self.assertEqual(primera.acuerdos, "Aprobar actividades del club.")
        self.assertEqual(primera.archivo.name, nombre)
        self.assertTrue(primera.archivo.storage.exists(nombre))
        self.assertEqual(VersionActa.objects.filter(estado="PUBLICADA").count(), 2)
        self.client.force_login(self.miembro)
        respuesta = self.client.get(reverse("institucional:acta_detalle", args=[primera.acta_id]))
        self.assertContains(respuesta, "Acuerdo corregido")
        self.assertContains(respuesta, "Aprobar actividades del club.")

    def test_no_se_modifica_publicada_y_correccion_exige_motivo(self):
        version = self.crear()
        services.publicar_acta(usuario=self.secretaria, version_id=version.pk)
        with self.assertRaises(ValidationError):
            services.editar_acta(usuario=self.secretaria, version_id=version.pk, datos=self.datos())
        version.acuerdos = "Cambio silencioso"
        with self.assertRaises(ValidationError):
            version.save()
        with self.assertRaises(ValidationError):
            services.nueva_version_acta(usuario=self.secretaria, acta_id=version.acta_id, datos=self.datos())
        with self.assertRaises(ValidationError):
            version.delete()

    def test_usuario_sin_pertenencia_no_consulta_y_retiro_grupo_impide_publicar(self):
        version = self.crear()
        self.client.force_login(self.ajeno)
        self.assertEqual(self.client.get(reverse("institucional:actas")).status_code, 403)
        self.client.force_login(self.secretaria)
        self.secretaria.groups.clear()
        self.assertEqual(self.client.post(reverse("institucional:acta_publicar", args=[version.pk])).status_code, 403)

    def test_publicacion_requiere_post_csrf_y_no_duplica(self):
        version = self.crear()
        self.client.force_login(self.secretaria)
        url = reverse("institucional:acta_publicar", args=[version.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.secretaria)
        self.assertEqual(cliente.post(url).status_code, 403)
        services.publicar_acta(usuario=self.secretaria, version_id=version.pk)
        with self.assertRaises(ValidationError):
            services.publicar_acta(usuario=self.secretaria, version_id=version.pk)
        self.assertEqual(Auditoria.objects.filter(accion="ACTA_PUBLICADA").count(), 1)

    def test_error_auditoria_revierte_publicacion_y_creacion(self):
        version = self.crear()
        with patch("institucional.services.registrar_auditoria", side_effect=RuntimeError("Fallo")):
            with self.assertRaises(RuntimeError):
                services.publicar_acta(usuario=self.secretaria, version_id=version.pk)
        version.refresh_from_db()
        self.assertEqual(version.estado, "BORRADOR")
        with patch("institucional.services.registrar_auditoria", side_effect=RuntimeError("Fallo")):
            with self.assertRaises(RuntimeError):
                services.crear_acta(usuario=self.secretaria, codigo="2026-02", datos=self.datos(), archivo=pdf())
        self.assertEqual(Acta.objects.count(), 1)
        self.assertEqual(list(self.raiz.rglob("*.pdf")), [])

    def test_pdf_adjunto_perdido_no_se_publica_como_si_estuviera_disponible(self):
        version = self.crear(pdf())
        version.archivo.storage.delete(version.archivo.name)
        with self.assertRaises(ValidationError):
            services.publicar_acta(usuario=self.secretaria, version_id=version.pk)
        version.refresh_from_db()
        self.assertEqual(version.estado, "BORRADOR")

    def test_auditoria_no_copia_textos_de_borrador_y_conserva_trazabilidad(self):
        previo = Auditoria.objects.create(usuario=self.admin, accion="REGISTRO_PREVIO", entidad="OtraEntidad", detalle={"conservar": "Auditoría existente"})
        inicial = "ACUERDO_RESERVADO_INICIAL_8941"
        corregido = "ACUERDO_RESERVADO_CORREGIDO_6273"
        datos = self.datos(titulo=f"Título reservado {inicial}", acuerdos=inicial, motivo_cambio=f"Detalle reservado {inicial}")
        version = services.crear_acta(usuario=self.secretaria, codigo="2026-PRIVADA", datos=datos)
        services.editar_acta(usuario=self.secretaria, version_id=version.pk, datos={**datos, "acuerdos": corregido})
        registros = Auditoria.objects.filter(entidad="VersionActa", entidad_id=version.pk)
        detalle = json.dumps(list(registros.values_list("detalle", flat=True)))
        self.assertNotIn(inicial, detalle)
        self.assertNotIn(corregido, detalle)
        cambio = registros.get(accion="ACTA_BORRADOR_MODIFICADO")
        self.assertEqual(cambio.detalle["version_id"], version.pk)
        self.assertEqual(cambio.detalle["despues"]["acta_id"], version.acta_id)
        self.assertEqual(cambio.detalle["despues"]["numero"], 1)
        self.assertEqual(cambio.detalle["campos_modificados"], ["acuerdos"])
        self.assertEqual(cambio.usuario, self.secretaria)
        self.assertEqual(cambio.detalle["antes"]["estado"], "BORRADOR")
        version.refresh_from_db()
        self.assertEqual(version.acuerdos, corregido)
        previo.refresh_from_db()
        self.assertEqual(previo.detalle, {"conservar": "Auditoría existente"})

    def test_publicacion_y_correccion_conservan_versiones_sin_copiar_acuerdos_en_auditoria(self):
        inicial = "ACUERDO_PUBLICADO_ORIGINAL_3851"
        correccion = "ACUERDO_PUBLICADO_CORREGIDO_9532"
        primera = services.crear_acta(usuario=self.secretaria, codigo="2026-HISTORIAL", datos=self.datos(acuerdos=inicial))
        services.publicar_acta(usuario=self.secretaria, version_id=primera.pk)
        segunda = services.nueva_version_acta(usuario=self.secretaria, acta_id=primera.acta_id, datos=self.datos(acuerdos=correccion, motivo_cambio="Corrección de transcripción"))
        services.publicar_acta(usuario=self.secretaria, version_id=segunda.pk)
        registros = Auditoria.objects.filter(entidad="VersionActa", entidad_id__in=[primera.pk, segunda.pk])
        detalle = json.dumps(list(registros.values_list("detalle", flat=True)))
        self.assertNotIn(inicial, detalle)
        self.assertNotIn(correccion, detalle)
        self.assertEqual(registros.filter(accion="ACTA_PUBLICADA").count(), 2)
        self.assertEqual(VersionActa.objects.get(pk=primera.pk).acuerdos, inicial)
        self.assertEqual(VersionActa.objects.get(pk=segunda.pk).acuerdos, correccion)
