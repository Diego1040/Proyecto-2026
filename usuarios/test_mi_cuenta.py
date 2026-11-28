from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import Apoderado, Auditoria, Jugador, Usuario


class MiCuentaTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            rut="11111111-1",
            password="ClaveSegura-2026",
            email="cuenta@example.com",
            first_name="Nombre",
            last_name="Original",
        )
        self.url = reverse("editar_mi_cuenta")

    def test_usuario_autenticado_puede_ver_sus_datos(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Mis datos personales")
        self.assertContains(respuesta, "cuenta@example.com")

    def test_usuario_no_autenticado_es_enviado_al_login(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    def test_usuario_actualiza_solo_sus_datos_generales(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(self.url, {
            "first_name": "Nombre Nuevo",
            "last_name": "Apellido Nuevo",
            "email": "nuevo@example.com",
            "telefono": "+56 9 1234 5678",
        })
        self.assertRedirects(respuesta, self.url)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, "Nombre Nuevo")
        self.assertEqual(self.usuario.last_name, "Apellido Nuevo")
        self.assertEqual(self.usuario.email, "nuevo@example.com")
        self.assertEqual(self.usuario.telefono, "+56 9 1234 5678")
        self.assertTrue(Auditoria.objects.filter(
            usuario=self.usuario,
            accion="ACTUALIZACION_DATOS_CUENTA",
            entidad="Usuario",
        ).exists())

    def test_post_no_permite_alterar_rut_estado_ni_permisos(self):
        self.client.force_login(self.usuario)
        self.client.post(self.url, {
            "first_name": "Nombre",
            "last_name": "Original",
            "email": "cuenta@example.com",
            "telefono": "12345678",
            "rut": "22222222-2",
            "is_active": "false",
            "is_superuser": "true",
            "is_staff": "true",
        })
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.rut, "11111111-1")
        self.assertTrue(self.usuario.is_active)
        self.assertFalse(self.usuario.is_superuser)
        self.assertFalse(self.usuario.is_staff)

    def test_datos_de_perfiles_vinculados_se_conservan_por_separado(self):
        apoderado = Apoderado.objects.create(
            usuario=self.usuario,
            rut=self.usuario.rut,
            nombres="Nombre Apoderado",
            apellidos="Apellido Apoderado",
            telefono="+56 9 1111 1111",
            email="apoderado@example.com",
        )
        jugador = Jugador.objects.create(
            usuario=self.usuario,
            rut=self.usuario.rut,
            nombres="Nombre Jugador",
            apellidos="Apellido Jugador",
            fecha_nacimiento=date(1990, 3, 10),
            rama=Jugador.Rama.VARONES,
            telefono="+56 9 2222 2222",
            email="jugador@example.com",
        )
        self.client.force_login(self.usuario)
        self.client.post(self.url, {
            "first_name": "Cuenta Actualizada",
            "last_name": "Nombre General",
            "email": "cuenta-nueva@example.com",
            "telefono": "+56 9 3333 3333",
        })

        apoderado.refresh_from_db()
        jugador.refresh_from_db()
        self.assertEqual(apoderado.nombres, "Nombre Apoderado")
        self.assertEqual(apoderado.email, "apoderado@example.com")
        self.assertEqual(apoderado.telefono, "+56 9 1111 1111")
        self.assertEqual(jugador.nombres, "Nombre Jugador")
        self.assertEqual(jugador.email, "jugador@example.com")
        self.assertEqual(jugador.telefono, "+56 9 2222 2222")

    def test_cuenta_edita_solo_su_propio_registro(self):
        otro = Usuario.objects.create_user(
            rut="20347119-K",
            password="OtraClaveSegura-2026",
            email="otro@example.com",
            first_name="Otra Persona",
        )
        self.client.force_login(self.usuario)
        self.client.post(self.url, {
            "first_name": "Cambio Propio",
            "last_name": "",
            "email": "cuenta@example.com",
            "telefono": "",
            "usuario_id": str(otro.pk),
        })
        otro.refresh_from_db()
        self.assertEqual(otro.first_name, "Otra Persona")
