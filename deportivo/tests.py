from django.test import TestCase

# Create your tests here.
# NUEVO (HU-07)
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import Auditoria, Categoria, Jugador

from .models import Asistencia, Entrenamiento, PerfilEntrenador


class AsistenciaTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", verbosity=0)
        Usuario = get_user_model()

        cls.u15 = Categoria.objects.get(nombre="U15 Varones")
        cls.u13 = Categoria.objects.get(nombre="U13 Damas")

        cls.entrenador = Usuario.objects.create_user(rut="33333333-3", password="clave-segura-123")
        cls.entrenador.groups.add(Group.objects.get_or_create(name="Entrenador")[0])
        perfil = PerfilEntrenador.objects.create(usuario=cls.entrenador)
        perfil.categorias.add(cls.u15)

        cls.secretaria = Usuario.objects.create_user(rut="22222222-2", password="clave-segura-123")
        cls.secretaria.groups.add(Group.objects.get_or_create(name="Administración")[0])

        cls.otro = Usuario.objects.create_user(rut="11111111-1", password="clave-segura-123")

        cls.tomas = Jugador.objects.create(
            rut="22333444-K", nombres="Tomas", apellidos="Vergara",
            fecha_nacimiento=date(2012, 2, 1), rama=Categoria.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO, categoria_actual=cls.u15,
        )
        cls.pendiente = Jugador.objects.create(
            rut="22444555-5", nombres="Martin", apellidos="Vergara",
            fecha_nacimiento=date(2012, 12, 20), rama=Categoria.Rama.VARONES,
            estado=Jugador.Estado.PENDIENTE, categoria_actual=cls.u15,
        )

    def crear_entrenamiento(self, fecha=None, categoria=None):
        return Entrenamiento.objects.create(
            categoria=categoria or self.u15,
            nombre="Técnico",
            duracion=90,
            fecha=fecha or timezone.localdate(),
            creado_por=self.entrenador,
        )

    def test_entrenador_va_directo_a_entrenamientos(self):
        self.client.force_login(self.entrenador)
        respuesta = self.client.get(reverse("panel"))
        self.assertRedirects(respuesta, reverse("deportivo:entrenamientos"), fetch_redirect_response=False)

    def test_usuario_sin_rol_no_entra(self):
        self.client.force_login(self.otro)
        respuesta = self.client.get(reverse("deportivo:entrenamientos"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertNotEqual(respuesta.url, reverse("deportivo:entrenamientos"))

    def test_entrenador_crea_entrenamiento_de_su_categoria(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:entrenamientos"), {
            "categoria_id": self.u15.pk, "nombre": "Táctico",
            "fecha": timezone.localdate().isoformat(), "duracion": 60,
        })
        self.assertTrue(Entrenamiento.objects.filter(categoria=self.u15, creado_por=self.entrenador).exists())

    def test_no_crea_entrenamiento_con_datos_vacios(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:entrenamientos"), {
            "categoria_id": self.u15.pk, "nombre": "",
            "fecha": "", "duracion": "",
        })
        self.assertFalse(Entrenamiento.objects.exists())

    def test_entrenador_no_crea_en_categoria_ajena(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:entrenamientos"), {
            "categoria_id": self.u13.pk, "nombre": "X",
            "fecha": timezone.localdate().isoformat(), "duracion": 60,
        })
        self.assertFalse(Entrenamiento.objects.filter(categoria=self.u13).exists())

    def test_entrenador_no_ve_entrenamiento_de_categoria_ajena(self):
        ajeno = self.crear_entrenamiento(categoria=self.u13)
        self.client.force_login(self.entrenador)
        respuesta = self.client.get(reverse("deportivo:tomar_asistencia", args=[ajeno.pk]))
        self.assertEqual(respuesta.status_code, 404)

    def test_lista_solo_muestra_jugadores_activos(self):
        e = self.crear_entrenamiento()
        self.client.force_login(self.entrenador)
        respuesta = self.client.get(reverse("deportivo:tomar_asistencia", args=[e.pk]))
        self.assertContains(respuesta, "Tomas")
        self.assertNotContains(respuesta, "Martin")

    def test_registra_asistencia_con_fecha_y_usuario(self):
        e = self.crear_entrenamiento()
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:tomar_asistencia", args=[e.pk]), {
            f"estado_{self.tomas.pk}": "AUSENTE",
        })
        asistencia = Asistencia.objects.get(entrenamiento=e, jugador=self.tomas)
        self.assertEqual(asistencia.estado, "AUSENTE")
        self.assertEqual(asistencia.registrado_por, self.entrenador)
        self.assertIsNotNone(asistencia.registrado_en)

    def test_no_registra_jugador_pendiente_aunque_lo_envien(self):
        e = self.crear_entrenamiento()
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:tomar_asistencia", args=[e.pk]), {
            f"estado_{self.pendiente.pk}": "PRESENTE",
        })
        self.assertFalse(Asistencia.objects.filter(jugador=self.pendiente).exists())

    def test_entrenador_no_modifica_despues_de_48_horas(self):
        e = self.crear_entrenamiento(fecha=timezone.localdate() - timedelta(days=4))
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:tomar_asistencia", args=[e.pk]), {
            f"estado_{self.tomas.pk}": "PRESENTE",
        })
        self.assertFalse(Asistencia.objects.filter(entrenamiento=e).exists())

    def test_administracion_modifica_antigua_solo_con_motivo(self):
        e = self.crear_entrenamiento(fecha=timezone.localdate() - timedelta(days=4))
        self.client.force_login(self.secretaria)
        url = reverse("deportivo:tomar_asistencia", args=[e.pk])

        self.client.post(url, {f"estado_{self.tomas.pk}": "PRESENTE"})
        self.assertFalse(Asistencia.objects.filter(entrenamiento=e).exists())

        self.client.post(url, {
            f"estado_{self.tomas.pk}": "PRESENTE",
            "motivo": "El entrenador avisó que sí asistió",
        })
        asistencia = Asistencia.objects.get(entrenamiento=e)
        self.assertEqual(asistencia.motivo_modificacion, "El entrenador avisó que sí asistió")
        self.assertTrue(
            Auditoria.objects.filter(accion="ASISTENCIA_MODIFICADA_FUERA_DE_PLAZO").exists()
        )
