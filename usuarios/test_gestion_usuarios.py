from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from .models import Usuario


class GestionUsuariosConsultaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrador = Usuario.objects.create_user(
            rut="12345678-5",
            password="ClaveSegura.123",
            email="admin@ayllubasket.cl",
            first_name="Admin",
            last_name="Prueba",
        )
        cls.cuenta_inactiva = Usuario.objects.create_user(
            rut="20347119-K",
            password="ClaveSegura.123",
            email="inactiva@ayllubasket.cl",
            is_active=False,
        )
        cls.cuenta_sin_permiso = Usuario.objects.create_user(
            rut="11111111-1",
            password="ClaveSegura.123",
            email="sinpermiso@ayllubasket.cl",
        )
        cls.grupo_administracion = Group.objects.create(name="Administración")
        permiso = Permission.objects.get(
            content_type__app_label="usuarios",
            content_type__model="usuario",
            codename="view_usuario",
        )
        cls.grupo_administracion.permissions.add(permiso)
        cls.administrador.groups.add(cls.grupo_administracion)

    def test_usuario_no_autenticado_debe_iniciar_sesion(self):
        respuesta = self.client.get(reverse("gestion_usuarios"))
        self.assertEqual(respuesta.status_code, 302)

    def test_usuario_sin_permiso_no_puede_ver_el_listado(self):
        self.client.force_login(self.cuenta_sin_permiso)
        respuesta = self.client.get(reverse("gestion_usuarios"))
        self.assertEqual(respuesta.status_code, 403)

    def test_administracion_puede_ver_todas_las_cuentas(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(reverse("gestion_usuarios"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "12345678-5")
        self.assertContains(respuesta, "20347119-K")
        self.assertContains(respuesta, "Sin perfil asociado")

    def test_busqueda_por_rut_filtra_las_cuentas(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(
            reverse("gestion_usuarios"),
            {"q": "20347119-K"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "20347119-K")
        self.assertNotContains(respuesta, "12345678-5")

    def test_filtro_de_estado_muestra_cuentas_inactivas(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(
            reverse("gestion_usuarios"),
            {"estado": "inactiva"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "20347119-K")
        self.assertNotContains(respuesta, "12345678-5")
        self.assertNotContains(respuesta, "11111111-1")

    def test_administracion_puede_consultar_detalle_sin_modificarlo(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(
            reverse("detalle_usuario", args=[self.cuenta_inactiva.pk])
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "20347119-K")
        self.assertContains(respuesta, "Inactiva")
