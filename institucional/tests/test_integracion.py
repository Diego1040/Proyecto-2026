from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse

from institucional import services
from institucional.models import DocumentoNormativo, VersionActa, VersionDocumentoNormativo

from .base import BaseInstitucionalTest, pdf


class IntegracionTest(BaseInstitucionalTest):
    def test_panel_y_portada_muestran_accesos_segun_rol_sin_quitar_los_existentes(self):
        for usuario, texto in ((self.admin, "Reglamentos y normativas"), (self.secretaria, "Actas"), (self.comite, "Comité"), (self.miembro, "Reglamentos y normativas")):
            with self.subTest(usuario=usuario.pk):
                self.client.force_login(usuario)
                panel = self.client.get(reverse("panel"))
                self.assertContains(panel, "Ingresar al área institucional")
                self.assertNotContains(panel, "Tu cuenta todavía no tiene un perfil asociado")
                inicio = self.client.get(reverse("institucional:inicio"))
                self.assertContains(inicio, texto)
                if usuario != self.comite:
                    self.assertNotContains(inicio, "Comité de Disciplina")
        self.client.force_login(self.admin)
        panel = self.client.get(reverse("panel"))
        for ruta in ("importacion_jugadores", "deportivo:nominas", "deportivo:revisar_lesiones", "solicitudes_administracion"):
            self.assertContains(panel, reverse(ruta))
        self.client.force_login(self.ajeno)
        self.assertNotContains(self.client.get(reverse("panel")), "Ingresar al área institucional")

    def test_tesoreria_conserva_redireccion_y_cuenta_multirrol_tiene_acceso_desde_portada(self):
        tesoreria, _ = Group.objects.get_or_create(name="Tesorería")
        self.comite.groups.add(tesoreria)
        self.client.force_login(self.comite)
        self.assertRedirects(self.client.get(reverse("panel")), reverse("finanzas:tesoreria"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("inicio")), reverse("institucional:inicio"))
        self.assertContains(self.client.get(reverse("institucional:inicio")), "Ingresar al Comité")

    def test_tesoreria_con_secretaria_o_comite_descubre_enlace_y_puede_volver(self):
        tesoreria, _ = Group.objects.get_or_create(name="Tesorería")
        for usuario, nombre_ruta in ((self.secretaria, "actas"), (self.comite, "sanciones")):
            with self.subTest(usuario=usuario.pk):
                usuario.groups.add(tesoreria)
                self.client.force_login(usuario)
                respuesta = self.client.get(reverse("panel"), follow=True)
                self.assertEqual(respuesta.redirect_chain, [(reverse("finanzas:tesoreria"), 302)])
                self.assertContains(respuesta, f'<a href="{reverse("institucional:inicio")}">Ingresar al área institucional</a>', html=True)
                institucional = self.client.get(reverse("institucional:inicio"))
                self.assertContains(institucional, f'<a href="{reverse("finanzas:tesoreria")}">Tesorería</a>', html=True)
                self.assertContains(institucional, reverse(f"institucional:{nombre_ruta}"))
                self.assertEqual(self.client.get(reverse(f"institucional:{nombre_ruta}")).status_code, 200)
                self.assertEqual(self.client.get(reverse("finanzas:tesoreria")).status_code, 200)

    def test_tesoreria_habilitada_consulta_como_integrante_del_club(self):
        tesoreria, _ = Group.objects.get_or_create(name="Tesorería")
        self.ajeno.groups.add(tesoreria)
        self.client.force_login(self.ajeno)
        respuesta = self.client.get(reverse("panel"), follow=True)
        self.assertEqual(respuesta.redirect_chain, [(reverse("finanzas:tesoreria"), 302)])
        self.assertContains(respuesta, "Ingresar al área institucional")
        self.assertEqual(self.client.get(reverse("institucional:inicio")).status_code, 200)

    def test_autorizacion_manual_desde_interfaz_y_revocacion(self):
        self.client.force_login(self.admin)
        for accion in ("autorizar", "revocar"):
            respuesta = self.client.post(reverse("institucional:miembros"), {"destinatario": self.ajeno.pk, "accion": accion, "motivo": "Comprobación por Administración"})
            self.assertEqual(respuesta.status_code, 302)
            self.client.force_login(self.ajeno)
            self.assertEqual(self.client.get(reverse("institucional:actas")).status_code, 200 if accion == "autorizar" else 403)
            self.client.force_login(self.admin)

    def test_edicion_y_nuevas_versiones_por_formulario(self):
        self.client.force_login(self.admin)
        version = services.crear_documento(usuario=self.admin, codigo="R-01", tipo="REGLAMENTO", datos=self.datos_documento(), archivo=pdf())
        datos = self.datos_documento(titulo="Normativa revisada")
        self.assertEqual(self.client.get(reverse("institucional:documento_editar", args=[version.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("institucional:documento_editar", args=[version.pk]), datos).status_code, 302)
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        datos.update(version="2.0", motivo_cambio="Actualización institucional", archivo=pdf())
        self.assertEqual(self.client.get(reverse("institucional:documento_version_nueva", args=[version.documento_id])).status_code, 200)
        self.assertEqual(self.client.post(reverse("institucional:documento_version_nueva", args=[version.documento_id]), datos).status_code, 302)
        self.assertEqual(VersionDocumentoNormativo.objects.count(), 2)

    def test_errores_de_formulario_no_publican_ni_exponen_pdf(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse("institucional:documento_nuevo"), {"titulo": "Incompleto"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(DocumentoNormativo.objects.exists())
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.get(reverse("institucional:miembros")).status_code, 403)

    def test_configuracion_no_reemplaza_permisos_de_otras_aplicaciones(self):
        from django.contrib.auth.models import Permission

        grupo = Group.objects.get(name="Administración")
        previo = Permission.objects.filter(content_type__app_label="usuarios").first()
        grupo.permissions.add(previo)
        call_command("configurar_institucional", stdout=StringIO())
        self.assertTrue(grupo.permissions.filter(pk=previo.pk).exists())
