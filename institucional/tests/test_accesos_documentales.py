from datetime import date, timedelta

from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from institucional import permisos, services
from institucional.forms import DocumentoNuevoForm
from institucional.models import VersionActa, VersionDocumentoNormativo
from usuarios.models import Apoderado, ApoderadoJugador, Auditoria, Jugador, SolicitudInscripcion, Usuario
from usuarios.services import completar_activacion
from usuarios.tokens import activacion_token_generator

from .base import BaseInstitucionalTest, pdf, rut


class ConsultaActasHabilitadasTest(BaseInstitucionalTest):
    def setUp(self):
        super().setUp()
        datos = {"titulo": "Acta publicada para el club", "fecha_reunion": timezone.localdate(), "acuerdos": "Acuerdos publicados.", "motivo_cambio": ""}
        self.publicada = services.crear_acta(usuario=self.secretaria, codigo="PUBLICADA-01", datos=datos)
        services.publicar_acta(usuario=self.secretaria, version_id=self.publicada.pk)
        self.borrador = services.crear_acta(usuario=self.secretaria, codigo="BORRADOR-01", datos={**datos, "titulo": "Borrador reservado", "acuerdos": "Acuerdos todavía reservados."})

    def habilitar_credencial(self, usuario):
        usuario.set_password("ClaveInstitucionalSegura2026!")
        usuario.save()

    def historico(self, usuario, estado="ACTIVO"):
        return Jugador.objects.create(usuario=usuario, rut=usuario.rut, nombres="Histórico", apellidos="Habilitado", fecha_nacimiento=date(1995, 1, 1), rama="VARONES", estado=estado)

    def test_todos_los_roles_del_club_consultan_publicadas_sin_grupo_manual(self):
        for nombre in ("Administración", "Secretaría", "Tesorería", "Entrenador", "Comité de Disciplina"):
            with self.subTest(rol=nombre):
                self.ajeno.groups.clear()
                self.ajeno.groups.add(Group.objects.get_or_create(name=nombre)[0])
                self.assertFalse(self.ajeno.groups.filter(name="Miembros autorizados").exists())
                self.client.force_login(self.ajeno)
                self.assertContains(self.client.get(reverse("institucional:acta_detalle", args=[self.publicada.acta_id])), "Acuerdos publicados.")
                borrador = self.client.get(reverse("institucional:acta_detalle", args=[self.borrador.acta_id]))
                self.assertEqual(borrador.status_code, 200 if nombre == "Secretaría" else 404)

    def test_historico_vinculado_con_credencial_habilitada_no_necesita_inscripcion(self):
        self.habilitar_credencial(self.ajeno)
        jugador = self.historico(self.ajeno)
        self.assertFalse(jugador.solicitudes_inscripcion.exists())
        self.assertFalse(self.ajeno.groups.exists())
        self.assertTrue(self.client.login(rut=self.ajeno.rut, password="ClaveInstitucionalSegura2026!"))
        self.assertEqual(self.client.get(reverse("institucional:acta_detalle", args=[self.publicada.acta_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("institucional:acta_detalle", args=[self.borrador.acta_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("institucional:acta_nueva")).status_code, 403)
        self.assertEqual(self.client.get(reverse("institucional:acta_editar", args=[self.borrador.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("institucional:acta_publicar", args=[self.borrador.pk])).status_code, 403)
        self.assertEqual(VersionActa.objects.get(pk=self.borrador.pk).estado, "BORRADOR")

    def test_cuenta_activa_que_inicia_sesion_sin_pertenencia_no_accede(self):
        self.habilitar_credencial(self.ajeno)
        self.ajeno.activado_en = timezone.now()
        self.ajeno.is_staff = self.ajeno.is_superuser = True
        self.ajeno.save()
        self.assertTrue(self.client.login(rut=self.ajeno.rut, password="ClaveInstitucionalSegura2026!"))
        self.assertFalse(permisos.es_miembro_autorizado(self.ajeno))
        self.assertEqual(self.client.get(reverse("institucional:actas")).status_code, 403)

    def test_anonimo_e_inactivo_no_consultan_actas(self):
        self.assertEqual(self.client.get(reverse("institucional:actas")).status_code, 302)
        self.admin.is_active = False
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("institucional:acta_detalle", args=[self.publicada.acta_id])).status_code, 302)

    def test_perfil_pendiente_y_vinculo_de_identidad_incorrecto_no_acreditan_pertenencia(self):
        self.habilitar_credencial(self.ajeno)
        jugador = self.historico(self.ajeno, estado="PENDIENTE")
        self.assertFalse(permisos.es_miembro_autorizado(self.ajeno))
        # Simula datos históricos incoherentes sin alterar las reglas del modelo.
        Jugador.objects.filter(pk=jugador.pk).update(estado="ACTIVO", rut=rut(24000001))
        self.assertFalse(permisos.es_miembro_autorizado(self.ajeno))

    def test_apoderado_habilitado_sin_solicitud_necesita_vinculo_actual(self):
        self.habilitar_credencial(self.ajeno)
        apoderado = Apoderado.objects.create(usuario=self.ajeno, rut=self.ajeno.rut, nombres="Responsable", apellidos="Histórico", telefono="123")
        jugador = Jugador.objects.create(rut=rut(24000002), nombres="Jugador", apellidos="Histórico", fecha_nacimiento=date(2014, 1, 1), rama="VARONES", estado="INACTIVO")
        vinculo = ApoderadoJugador.objects.create(apoderado=apoderado, jugador=jugador, parentesco="Madre", activo=True, puede_gestionar=True)
        self.assertTrue(permisos.es_miembro_autorizado(self.ajeno))
        vinculo.puede_gestionar = False
        vinculo.save()
        self.assertFalse(permisos.es_miembro_autorizado(self.ajeno))
        vinculo.puede_gestionar, vinculo.activo = True, False
        vinculo.save()
        self.assertFalse(permisos.es_miembro_autorizado(self.ajeno))

    def test_activacion_real_habilita_al_integrante_y_rechaza_cuenta_no_aprobada(self):
        cuenta = Usuario.objects.create_user(rut=rut(24000003), is_active=False)
        jugador = self.historico(cuenta)
        SolicitudInscripcion.objects.create(jugador=jugador, estado="APROBADA", procedencia="INDEPENDIENTE", consentimiento=True, usuario_autorizado=cuenta, revisado_por=self.admin, fecha_revision=timezone.now())
        formulario = SetPasswordForm(cuenta, {"new_password1": "ClaveActivacionSegura2026!", "new_password2": "ClaveActivacionSegura2026!"})
        self.assertTrue(formulario.is_valid())
        cuenta = completar_activacion(cuenta=cuenta, formulario=formulario, token=activacion_token_generator.make_token(cuenta))
        self.assertTrue(permisos.es_miembro_autorizado(cuenta))
        self.assertFalse(cuenta.groups.filter(name="Miembros autorizados").exists())
        pendiente = Usuario.objects.create_user(rut=rut(24000004), is_active=False)
        formulario = SetPasswordForm(pendiente, {"new_password1": "ClaveActivacionSegura2026!", "new_password2": "ClaveActivacionSegura2026!"})
        self.assertTrue(formulario.is_valid())
        with self.assertRaises(ValidationError):
            completar_activacion(cuenta=pendiente, formulario=formulario, token=activacion_token_generator.make_token(pendiente))
        pendiente.refresh_from_db()
        self.assertFalse(pendiente.is_active)


class ConsultaNormativaPublicaTest(BaseInstitucionalTest):
    def crear(self, codigo="PUBLICO-01", visibilidad="PUBLICO", publicar=True):
        version = services.crear_documento(usuario=self.admin, codigo=codigo, tipo="REGLAMENTO", datos=self.datos_documento(titulo=f"Reglamento {codigo}", visibilidad=visibilidad), archivo=pdf())
        if publicar:
            services.publicar_documento(usuario=self.admin, version_id=version.pk)
        return version

    def test_portada_enlaza_seccion_y_anonimo_consulta_y_descarga_publico_vigente(self):
        version = self.crear()
        portada = self.client.get(reverse("inicio"))
        self.assertContains(portada, "Reglamentos y normativas")
        self.assertContains(portada, reverse("institucional:documentos"))
        self.assertContains(self.client.get(reverse("institucional:documentos")), version.titulo)
        detalle = self.client.get(reverse("institucional:documento_detalle", args=[version.documento_id]))
        for texto in (version.titulo, "Público", "Vigente", "Publicación", "1.0"):
            self.assertContains(detalle, texto)
        self.assertNotContains(detalle, version.archivo.name)
        self.assertNotContains(detalle, "Historial de gestión")
        descarga = self.client.get(reverse("institucional:documento_descargar", args=[version.pk]))
        self.assertEqual(descarga.status_code, 200)
        self.assertTrue(b"".join(descarga.streaming_content).startswith(b"%PDF-"))
        self.assertIn("attachment", descarga["Content-Disposition"])
        self.assertIn("no-store", descarga["Cache-Control"])
        with self.assertRaises(NotImplementedError):
            version.archivo.storage.url(version.archivo.name)

    def test_anonimo_no_ve_internos_ni_borradores_por_urls_directas(self):
        interno = self.crear(codigo="INTERNO", visibilidad="INTERNO")
        borrador = self.crear(codigo="BORRADOR", publicar=False)
        listado = self.client.get(reverse("institucional:documentos"))
        for version in (interno, borrador):
            self.assertNotContains(listado, version.titulo)
            self.assertEqual(self.client.get(reverse("institucional:documento_detalle", args=[version.documento_id])).status_code, 404)
            self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[version.pk])).status_code, 404)

    def test_publico_historico_no_se_expone_y_hay_una_sola_vigente(self):
        primera = self.crear()
        segunda = services.nueva_version_documento(usuario=self.admin, documento_id=primera.documento_id, datos=self.datos_documento(version="2.0", visibilidad="PUBLICO", titulo="Reglamento actualizado", motivo_cambio="Revisión interna de la publicación"), archivo=pdf())
        services.publicar_documento(usuario=self.admin, version_id=segunda.pk)
        self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[primera.pk])).status_code, 404)
        detalle = self.client.get(reverse("institucional:documento_detalle", args=[primera.documento_id]))
        self.assertContains(detalle, segunda.titulo)
        self.assertNotContains(detalle, primera.titulo)
        self.assertNotContains(detalle, segunda.motivo_cambio)
        self.assertEqual(VersionDocumentoNormativo.objects.filter(documento_id=primera.documento_id, estado="VIGENTE").count(), 1)

    def test_club_consulta_interno_y_cuenta_no_autorizada_o_inactiva_no(self):
        interno = self.crear(visibilidad="INTERNO")
        detalle_url = reverse("institucional:documento_detalle", args=[interno.documento_id])
        descarga_url = reverse("institucional:documento_descargar", args=[interno.pk])
        for usuario in (self.admin, self.secretaria, self.comite, self.miembro):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(detalle_url).status_code, 200)
            descarga = self.client.get(descarga_url)
            self.assertEqual(descarga.status_code, 200)
            descarga.close()
        self.client.force_login(self.ajeno)
        self.assertEqual(self.client.get(detalle_url).status_code, 404)
        self.assertEqual(self.client.get(descarga_url).status_code, 404)
        self.admin.is_active = False
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(descarga_url).status_code, 404)

    def test_borrador_publico_no_hace_publica_la_version_interna_vigente(self):
        interno = self.crear(visibilidad="INTERNO")
        borrador = services.nueva_version_documento(usuario=self.admin, documento_id=interno.documento_id, datos=self.datos_documento(version="2.0", visibilidad="PUBLICO", motivo_cambio="Publicación para visitantes"), archivo=pdf())
        self.assertEqual(self.client.get(reverse("institucional:documento_detalle", args=[interno.documento_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[borrador.pk])).status_code, 404)
        services.publicar_documento(usuario=self.admin, version_id=borrador.pk)
        self.assertEqual(self.client.get(reverse("institucional:documento_detalle", args=[interno.documento_id])).status_code, 200)
        registro = Auditoria.objects.get(accion="NORMATIVA_PUBLICADA", entidad_id=borrador.pk)
        self.assertEqual(registro.detalle["despues"]["visibilidad"], "PUBLICO")

    def test_nueva_version_vuelve_a_interna_por_defecto_y_restringe_la_anterior(self):
        publica = self.crear()
        datos = self.datos_documento(version="2.0", motivo_cambio="Revisión para uso interno")
        datos.pop("visibilidad")
        interna = services.nueva_version_documento(usuario=self.admin, documento_id=publica.documento_id, datos=datos, archivo=pdf())
        self.assertEqual(interna.visibilidad, "INTERNO")
        services.publicar_documento(usuario=self.admin, version_id=interna.pk)
        for version in (publica, interna):
            self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[version.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("institucional:documento_detalle", args=[publica.documento_id])).status_code, 404)

    def test_formulario_interno_por_defecto_y_solo_administracion_publica(self):
        self.assertEqual(DocumentoNuevoForm().fields["visibilidad"].initial, "INTERNO")
        self.client.force_login(self.admin)
        datos = {**self.datos_documento(visibilidad="PUBLICO"), "codigo": "FORMULARIO", "tipo": "REGLAMENTO", "archivo": pdf()}
        self.assertEqual(self.client.post(reverse("institucional:documento_nuevo"), datos).status_code, 302)
        version = VersionDocumentoNormativo.objects.get()
        self.assertEqual(version.visibilidad, "PUBLICO")
        for usuario in (self.secretaria, self.comite, self.miembro, self.ajeno):
            self.client.force_login(usuario)
            self.assertEqual(self.client.post(reverse("institucional:documento_publicar", args=[version.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("institucional:documento_publicar", args=[version.pk])).status_code, 302)

    def test_visibilidad_publicada_es_inmutable_y_vigencia_futura_no_se_expone(self):
        version = self.crear()
        version.visibilidad = "INTERNO"
        with self.assertRaises(ValidationError):
            version.save()
        VersionDocumentoNormativo.objects.filter(pk=version.pk).update(vigente_desde=timezone.localdate() + timedelta(days=1))
        self.assertEqual(self.client.get(reverse("institucional:documento_detalle", args=[version.documento_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("institucional:documento_descargar", args=[version.pk])).status_code, 404)
