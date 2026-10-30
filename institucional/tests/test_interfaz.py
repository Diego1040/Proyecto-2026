from django.urls import reverse
from django.utils import timezone

from institucional import services
from .base import BaseInstitucionalTest, pdf


class InterfazInstitucionalTest(BaseInstitucionalTest):
    def datos_acta(self, **cambios):
        datos = {"titulo": "Reunión institucional", "fecha_reunion": timezone.localdate(),
                 "acuerdos": "Acuerdos que deben conservarse.", "motivo_cambio": ""}
        datos.update(cambios)
        return datos

    def crear_version(self, tipo, motivo=""):
        if tipo == "acta":
            return services.crear_acta(usuario=self.secretaria, codigo="ACT-UI", archivo=pdf(),
                                       datos=self.datos_acta(motivo_cambio=motivo))
        return services.crear_documento(usuario=self.admin, codigo="NOR-UI", tipo="REGLAMENTO",
                                        archivo=pdf(), datos=self.datos_documento(motivo_cambio=motivo))

    def publicar(self, tipo, version):
        operacion = services.publicar_acta if tipo == "acta" else services.publicar_documento
        operacion(usuario=self.secretaria if tipo == "acta" else self.admin, version_id=version.pk)

    def siguiente(self, tipo, version):
        if tipo == "acta":
            return services.nueva_version_acta(usuario=self.secretaria, acta_id=version.acta_id,
                                               datos=self.datos_acta(motivo_cambio="Corrección justificada"))
        return services.nueva_version_documento(usuario=self.admin, documento_id=version.documento_id,
                                                datos=self.datos_documento(version="2.0", motivo_cambio="Actualización justificada"))

    def test_primera_version_sin_justificacion_y_justificacion_existente_preservada(self):
        for tipo in ("acta", "documento"):
            with self.subTest(tipo=tipo):
                self.client.force_login(self.secretaria if tipo == "acta" else self.admin)
                nueva = self.client.get(reverse(f"institucional:{tipo}_nueva" if tipo == "acta" else "institucional:documento_nuevo"))
                self.assertNotIn("motivo_cambio", [f.name for f in nueva.context["form"].visible_fields()])
                version = self.crear_version(tipo, motivo="Justificación histórica que se conserva")
                nombre_pdf = version.archivo.name
                url = reverse(f"institucional:{tipo}_editar", args=[version.pk])
                edicion = self.client.get(url)
                self.assertContains(edicion, version.motivo_cambio)
                datos = self.datos_acta() if tipo == "acta" else self.datos_documento()
                datos.pop("motivo_cambio")
                datos["titulo"] = "Título revisado del borrador"
                self.assertEqual(self.client.post(url, datos).status_code, 302)
                version.refresh_from_db()
                self.assertEqual(version.motivo_cambio, "Justificación histórica que se conserva")
                self.assertEqual(version.archivo.name, nombre_pdf)
                self.assertEqual(version.titulo, datos["titulo"])

    def test_correccion_sin_justificacion_muestra_error_junto_al_campo_y_conserva_texto(self):
        for tipo in ("acta", "documento"):
            with self.subTest(tipo=tipo):
                version = self.crear_version(tipo)
                self.publicar(tipo, version)
                self.client.force_login(self.secretaria if tipo == "acta" else self.admin)
                datos = self.datos_acta() if tipo == "acta" else self.datos_documento(version="2.0")
                datos["titulo"] = "Texto escrito antes del error"
                padre = version.acta_id if tipo == "acta" else version.documento_id
                respuesta = self.client.post(reverse(f"institucional:{tipo}_version_nueva", args=[padre]), datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn("motivo_cambio", respuesta.context["form"].errors)
                self.assertEqual(respuesta.context["form"]["titulo"].value(), datos["titulo"])
                self.assertEqual(type(version).objects.count(), 1)

    def test_editar_segunda_version_no_borra_justificacion_si_se_envia_vacia(self):
        for tipo in ("acta", "documento"):
            with self.subTest(tipo=tipo):
                primera = self.crear_version(tipo)
                self.publicar(tipo, primera)
                version = self.siguiente(tipo, primera)
                motivo = version.motivo_cambio
                self.client.force_login(self.secretaria if tipo == "acta" else self.admin)
                datos = self.datos_acta() if tipo == "acta" else self.datos_documento(version="2.0")
                respuesta = self.client.post(reverse(f"institucional:{tipo}_editar", args=[version.pk]), datos)
                self.assertIn("motivo_cambio", respuesta.context["form"].errors)
                version.refresh_from_db()
                self.assertEqual(version.motivo_cambio, motivo)

    def test_borrador_oculta_nueva_version_sin_quitar_validacion_del_servidor(self):
        for tipo in ("acta", "documento"):
            with self.subTest(tipo=tipo):
                version = self.crear_version(tipo)
                self.client.force_login(self.secretaria if tipo == "acta" else self.admin)
                padre = version.acta_id if tipo == "acta" else version.documento_id
                url = reverse(f"institucional:{tipo}_version_nueva", args=[padre])
                detalle = self.client.get(reverse(f"institucional:{tipo}_detalle", args=[padre]))
                self.assertNotContains(detalle, f'href="{url}"')
                self.assertContains(detalle, reverse(f"institucional:{tipo}_editar", args=[version.pk]))
                datos = self.datos_acta(motivo_cambio="Corrección") if tipo == "acta" else self.datos_documento(version="2.0", motivo_cambio="Actualización")
                respuesta = self.client.post(url, datos)
                self.assertContains(respuesta, "Primero termina el borrador existente.")
                self.assertEqual(type(version).objects.count(), 1)

    def test_nueva_version_muestra_referencia_y_mantiene_interno_por_defecto(self):
        version = services.crear_documento(usuario=self.admin, codigo="PUB-UI", tipo="REGLAMENTO",
                                           archivo=pdf(), datos=self.datos_documento(visibilidad="PUBLICO"))
        services.publicar_documento(usuario=self.admin, version_id=version.pk)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("institucional:documento_version_nueva", args=[version.documento_id]))
        self.assertContains(respuesta, "PUB-UI")
        self.assertContains(respuesta, version.titulo)
        self.assertEqual(respuesta.context["form"]["visibilidad"].value(), "INTERNO")

    def test_pdf_faltante_desactiva_boton_pero_publicacion_directa_sigue_protegida(self):
        version = services.crear_documento(usuario=self.admin, codigo="SIN-PDF", tipo="REGLAMENTO",
                                           datos=self.datos_documento())
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("institucional:documento_detalle", args=[version.documento_id]))
        self.assertContains(respuesta, "Falta adjuntar el PDF")
        self.assertContains(respuesta, 'disabled aria-describedby="pdf-pendiente-')
        self.client.post(reverse("institucional:documento_publicar", args=[version.pk]))
        version.refresh_from_db()
        self.assertEqual(version.estado, "BORRADOR")

    def registrar(self):
        return services.registrar_sancion(usuario=self.comite, jugador=self.jugador_aprobado(),
                                          fecha=timezone.localdate(), motivo="Motivo del expediente")

    def test_resolver_y_anular_identifican_expediente_y_permiten_volver_al_detalle(self):
        sancion = self.registrar()
        self.client.force_login(self.comite)
        for accion, boton in (("resolver", "Resolver expediente"), ("anular", "Anular expediente")):
            with self.subTest(accion=accion):
                respuesta = self.client.get(reverse(f"institucional:sancion_{accion}", args=[sancion.pk]))
                self.assertContains(respuesta, str(sancion.jugador))
                self.assertContains(respuesta, "Estado actual")
                self.assertContains(respuesta, "Registrada")
                self.assertContains(respuesta, f'>{boton}</button>')
                self.assertContains(respuesta, reverse("institucional:sancion_detalle", args=[sancion.pk]))

    def test_resolucion_en_correccion_pendiente_conserva_texto_y_estado(self):
        sancion = self.registrar()
        sancion = services.corregir_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1,
                                           jugador=sancion.jugador, fecha=sancion.fecha, motivo=sancion.motivo,
                                           resolucion="Texto previo sin cerrar el expediente", justificacion="Anotación previa")
        self.client.force_login(self.comite)
        url = reverse("institucional:sancion_corregir", args=[sancion.pk])
        respuesta = self.client.get(url)
        self.assertContains(respuesta, sancion.resolucion)
        self.assertIn("resolucion", [f.name for f in respuesta.context["form"].visible_fields()])
        respuesta = self.client.post(url, {"jugador": sancion.jugador_id, "fecha": sancion.fecha,
                                           "motivo": "Motivo corregido", "resolucion": sancion.resolucion,
                                           "justificacion": "Corrección del motivo", "revision": sancion.revision})
        self.assertEqual(respuesta.status_code, 302)
        sancion.refresh_from_db()
        self.assertEqual(sancion.estado, "REGISTRADA")
        self.assertEqual(sancion.resolucion, "Texto previo sin cerrar el expediente")

    def test_error_de_resolucion_al_corregir_cerrada_se_muestra_en_su_campo(self):
        sancion = self.registrar()
        sancion = services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1,
                                           resolucion="Resolución que debe conservarse")
        self.client.force_login(self.comite)
        respuesta = self.client.post(reverse("institucional:sancion_corregir", args=[sancion.pk]), {
            "jugador": sancion.jugador_id, "fecha": sancion.fecha, "motivo": sancion.motivo,
            "resolucion": "", "justificacion": "Corrección", "revision": sancion.revision,
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("resolucion", respuesta.context["form"].errors)
        sancion.refresh_from_db()
        self.assertEqual(sancion.resolucion, "Resolución que debe conservarse")
