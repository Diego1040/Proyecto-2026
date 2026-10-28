from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from deportivo.models import Asistencia, Nomina, NominaJugador, ReporteLesion
from finanzas.models import Beca, Cuota, Pago
from institucional import services
from institucional.forms import SancionCorreccionForm, SancionNuevaForm
from institucional.models import EventoDisciplinario, Sancion
from usuarios.models import Auditoria, Jugador, PeriodoInactividad

from .base import BaseInstitucionalTest, rut


class DisciplinaTest(BaseInstitucionalTest):
    def setUp(self):
        super().setUp()
        self.jugador = self.jugador_aprobado()

    def registrar(self):
        return services.registrar_sancion(usuario=self.comite, jugador=self.jugador, fecha=timezone.localdate(), motivo="Motivo reservado del expediente")

    def test_comite_registra_desde_interfaz_y_consulta_con_bitacora(self):
        self.client.force_login(self.comite)
        respuesta = self.client.post(reverse("institucional:sancion_nueva"), {"jugador": self.jugador.pk, "fecha": timezone.localdate(), "motivo": "Motivo reservado del expediente"})
        self.assertEqual(respuesta.status_code, 302)
        sancion = Sancion.objects.get()
        self.assertEqual(sancion.estado, "REGISTRADA")
        self.assertEqual(sancion.creada_por, self.comite)
        detalle = self.client.get(reverse("institucional:sancion_detalle", args=[sancion.pk]))
        self.assertContains(detalle, "Motivo reservado del expediente")
        self.assertContains(detalle, "Bitácora privada")
        self.assertIn("no-store", detalle["Cache-Control"])
        self.assertEqual(list(sancion.eventos.values_list("accion", flat=True)), ["CONSULTADA", "REGISTRADA"])
        self.assertFalse(Auditoria.objects.filter(entidad__in=["Sancion", "EventoDisciplinario"]).exists())

    def test_nadie_fuera_del_comite_accede_por_urls_directas(self):
        sancion = self.registrar()
        self.ajeno.is_staff = self.ajeno.is_superuser = True
        self.ajeno.save()
        self.ajeno.user_permissions.add(Permission.objects.get(content_type__app_label="institucional", codename="view_sancion"))
        self.assertTrue(self.ajeno.has_perm("institucional.view_sancion"))
        for usuario in (self.admin, self.secretaria, self.miembro, self.ajeno):
            self.client.force_login(usuario)
            for nombre, args in (("sanciones", []), ("sancion_nueva", []), ("sancion_detalle", [sancion.pk]), ("sancion_corregir", [sancion.pk]), ("sancion_resolver", [sancion.pk]), ("sancion_anular", [sancion.pk])):
                with self.subTest(usuario=usuario.pk, ruta=nombre):
                    respuesta = self.client.get(reverse(f"institucional:{nombre}", args=args))
                    self.assertEqual(respuesta.status_code, 403)
                    self.assertNotContains(respuesta, sancion.motivo, status_code=403)
            with self.assertRaises(PermissionDenied):
                services.consultar_sancion(usuario=usuario, sancion_id=sancion.pk)
        self.assertEqual(sancion.eventos.count(), 1)

    def test_anonimo_inactivo_y_grupo_retirado_no_acceden(self):
        self.assertEqual(self.client.get(reverse("institucional:sanciones")).status_code, 302)
        self.comite.is_active = False
        self.comite.save()
        self.client.force_login(self.comite)
        self.assertEqual(self.client.get(reverse("institucional:sanciones")).status_code, 302)
        self.comite.is_active = True
        self.comite.save()
        self.client.force_login(self.comite)
        self.comite.groups.clear()
        self.assertEqual(self.client.get(reverse("institucional:sanciones")).status_code, 403)

    def test_correccion_exige_justificacion_y_guarda_antes_despues(self):
        sancion = self.registrar()
        datos = {"usuario": self.comite, "sancion_id": sancion.pk, "revision": 1, "jugador": self.jugador, "fecha": sancion.fecha, "motivo": "Motivo corregido", "resolucion": ""}
        with self.assertRaises(ValidationError):
            services.corregir_sancion(**datos, justificacion=" ")
        services.corregir_sancion(**datos, justificacion="Corrección de transcripción")
        evento = sancion.eventos.get(accion="CORREGIDA")
        self.assertEqual(evento.antes["motivo"], "Motivo reservado del expediente")
        self.assertEqual(evento.despues["motivo"], "Motivo corregido")
        self.assertEqual(evento.actor, self.comite)
        self.assertEqual(evento.justificacion, "Corrección de transcripción")

    def test_resolucion_obligatoria_y_responsable_registrado(self):
        sancion = self.registrar()
        with self.assertRaises(ValidationError):
            services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion=" ")
        resultado = services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Resolución del Comité")
        self.assertEqual(resultado.estado, "RESUELTA")
        self.assertEqual(resultado.resuelta_por, self.comite)
        self.assertIsNotNone(resultado.resuelta_en)
        self.assertTrue(resultado.eventos.filter(accion="RESUELTA").exists())

    def test_anulacion_cierra_con_resolucion_y_justificacion_y_conserva_historial(self):
        sancion = self.registrar()
        for resolucion, motivo in (("", "Error"), ("Se anula", "")):
            with self.assertRaises(ValidationError):
                services.anular_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion=resolucion, justificacion=motivo)
        anulada = services.anular_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Se anula el expediente", justificacion="Registro duplicado")
        self.assertEqual(anulada.estado, "ANULADA")
        self.assertEqual(anulada.eventos.count(), 2)
        with self.assertRaises(ValidationError):
            services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=2, resolucion="Otra")
        with self.assertRaises(ValidationError):
            anulada.delete()

    def test_resuelta_puede_corregirse_con_trazabilidad_sin_borrar_resolucion(self):
        sancion = self.registrar()
        services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Acuerdo inicial")
        datos = {"usuario": self.comite, "sancion_id": sancion.pk, "revision": 2, "jugador": self.jugador, "fecha": sancion.fecha, "motivo": sancion.motivo, "justificacion": "Aclaración del acuerdo"}
        with self.assertRaises(ValidationError):
            services.corregir_sancion(**datos, resolucion="")
        resultado = services.corregir_sancion(**datos, resolucion="Acuerdo aclarado")
        self.assertEqual(resultado.estado, "RESUELTA")
        evento = resultado.eventos.get(accion="CORREGIDA")
        self.assertEqual(evento.antes["resolucion"], "Acuerdo inicial")

    def test_revision_obsoleta_no_pierde_cambios_ni_crea_eventos(self):
        sancion = self.registrar()
        services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Acuerdo vigente")
        with self.assertRaises(ValidationError):
            services.anular_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Cambio obsoleto", justificacion="Error")
        sancion.refresh_from_db()
        self.assertEqual(sancion.resolucion, "Acuerdo vigente")
        self.assertEqual(sancion.eventos.count(), 2)

    def test_fallo_bitacora_revierte_creacion_y_resolucion(self):
        with patch("institucional.services.EventoDisciplinario.objects.create", side_effect=RuntimeError("Fallo")):
            with self.assertRaises(RuntimeError):
                self.registrar()
        self.assertFalse(Sancion.objects.exists())
        sancion = self.registrar()
        with patch("institucional.services.EventoDisciplinario.objects.create", side_effect=RuntimeError("Fallo")):
            with self.assertRaises(RuntimeError):
                services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Acuerdo")
        sancion.refresh_from_db()
        self.assertEqual(sancion.estado, "REGISTRADA")
        self.assertEqual(sancion.revision, 1)
        self.assertEqual(sancion.eventos.count(), 1)

    def test_bitacora_inmutable_y_sin_exposicion_en_django_admin(self):
        sancion = self.registrar()
        evento = sancion.eventos.get()
        evento.justificacion = "Cambio silencioso"
        with self.assertRaises(ValidationError):
            evento.save()
        with self.assertRaises(ValidationError):
            evento.delete()
        self.assertNotIn(Sancion, admin.site._registry)
        self.assertNotIn(EventoDisciplinario, admin.site._registry)
        self.assertNotIn(sancion.motivo, str(sancion))

    def test_sancion_sobre_inactivo_no_modifica_otras_historias(self):
        PeriodoInactividad.objects.create(jugador=self.jugador, motivo="LESION", fecha_inicio=timezone.localdate())
        modelos = (Jugador, PeriodoInactividad, Cuota, Pago, Beca, Asistencia, Nomina, NominaJugador, ReporteLesion)
        antes = {modelo: list(modelo.objects.order_by("pk").values()) for modelo in modelos}
        with patch("finanzas.services.jugador_bloqueado_por_morosidad", side_effect=AssertionError("No corresponde")):
            sancion = self.registrar()
            services.resolver_sancion(usuario=self.comite, sancion_id=sancion.pk, revision=1, resolucion="Sin efectos automáticos")
        for modelo in modelos:
            self.assertEqual(list(modelo.objects.order_by("pk").values()), antes[modelo], modelo.__name__)
        self.assertFalse(Auditoria.objects.exists())

    def test_formularios_de_cierre_y_correccion_y_csrf(self):
        sancion = self.registrar()
        self.client.force_login(self.comite)
        for nombre in ("sancion_corregir", "sancion_resolver", "sancion_anular"):
            self.assertEqual(self.client.get(reverse(f"institucional:{nombre}", args=[sancion.pk])).status_code, 200)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.comite)
        url = reverse("institucional:sancion_resolver", args=[sancion.pk])
        self.assertEqual(cliente.post(url, {"revision": 1, "resolucion": "Acuerdo"}).status_code, 403)
        self.assertEqual(self.client.post(url, {"revision": 1, "resolucion": "Acuerdo"}).status_code, 302)
        sancion.refresh_from_db()
        self.assertEqual(sancion.estado, "RESUELTA")

    def test_texto_se_escapa_y_no_aparece_en_panel_ajeno(self):
        sancion = services.registrar_sancion(usuario=self.comite, jugador=self.jugador, fecha=timezone.localdate(), motivo="<script>alert('confidencial')</script>")
        self.client.force_login(self.comite)
        detalle = self.client.get(reverse("institucional:sancion_detalle", args=[sancion.pk]))
        self.assertNotContains(detalle, "<script>")
        self.assertContains(detalle, "&lt;script&gt;")
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("panel")), "confidencial")

    def test_ambos_selectores_incluyen_aprobado_temporalmente_inactivo_sin_modificarlo(self):
        PeriodoInactividad.objects.create(jugador=self.jugador, motivo="RECESO_PERSONAL", fecha_inicio=timezone.localdate())
        self.jugador.refresh_from_db()
        antes = list(Jugador.objects.values())
        self.assertEqual(self.jugador.estado, "INACTIVO")
        for clase in (SancionNuevaForm, SancionCorreccionForm):
            with self.subTest(formulario=clase.__name__):
                self.assertTrue(clase().fields["jugador"].queryset.filter(pk=self.jugador.pk).exists())
        self.assertEqual(list(Jugador.objects.values()), antes)

    def test_selector_historico_se_conserva_hasta_confirmar_politica_de_pertenencia(self):
        historico = Jugador.objects.create(rut=rut(23000001), nombres="Histórico", apellidos="Sin solicitud", fecha_nacimiento=self.jugador.fecha_nacimiento, rama="VARONES", estado="INACTIVO")
        self.assertFalse(historico.solicitudes_inscripcion.filter(estado="APROBADA").exists())
        for clase in (SancionNuevaForm, SancionCorreccionForm):
            self.assertTrue(clase().fields["jugador"].queryset.filter(pk=historico.pk).exists())
