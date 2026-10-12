from datetime import date, timedelta
 
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
 
from usuarios.models import Auditoria, Categoria, Jugador, Apoderado, ApoderadoJugador
 
from .models import Asistencia, Entrenamiento, PerfilEntrenador, Evento
 
 
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
 
    def test_panel_ofrece_acceso_a_entrenamientos(self):
        self.client.force_login(self.entrenador)
        respuesta = self.client.get(reverse("panel"))
        self.assertContains(respuesta, reverse("deportivo:entrenamientos"))
 
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
            # CAMBIO (HU-06): campos obligatorios de la planificacion
            "hora_inicio": "18:30", "objetivo": "Defensa en zona",
            "responsable_id": self.entrenador.pk,
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
 
    def test_apoderado_ve_asistencia_del_mes(self):
        from usuarios.models import Apoderado, ApoderadoJugador
 
        apoderado = Apoderado.objects.create(
            usuario=self.otro, rut="11111111-1",
            nombres="Carolina", apellidos="Vergara", telefono="1",
        )
        ApoderadoJugador.objects.create(
            apoderado=apoderado, jugador=self.tomas, parentesco="Madre",
            es_principal=True, puede_gestionar=True, activo=True,
        )
 
        for estado in ["PRESENTE", "PRESENTE", "PRESENTE", "AUSENTE"]:
            e = self.crear_entrenamiento()
            Asistencia.objects.create(
                entrenamiento=e, jugador=self.tomas,
                estado=estado, registrado_por=self.entrenador,
            )
 
        self.client.force_login(self.otro)
        self.assertContains(self.client.get(reverse("panel")), reverse("perfil_apoderado"))
        respuesta = self.client.get(reverse("perfil_apoderado"))
        self.assertContains(respuesta, "75%")
 
 
 
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# NUEVO (HU-06) - Miguel: pruebas de la planificacion
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
class PlanificacionTest(TestCase):
 
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", verbosity=0)
        Usuario = get_user_model()
        grupo = Group.objects.get_or_create(name="Entrenador")[0]
 
        cls.u15 = Categoria.objects.get(nombre="U15 Varones")
        cls.u13 = Categoria.objects.get(nombre="U13 Damas")
 
        cls.entrenador = Usuario.objects.create_user(rut="33333333-3", password="clave-segura-123")
        cls.entrenador.groups.add(grupo)
        PerfilEntrenador.objects.create(usuario=cls.entrenador).categorias.add(cls.u15)
 
        cls.ayudante = Usuario.objects.create_user(rut="44444444-4", password="clave-segura-123")
        cls.ayudante.groups.add(grupo)
        PerfilEntrenador.objects.create(usuario=cls.ayudante).categorias.add(cls.u15)
 
        cls.otro_entrenador = Usuario.objects.create_user(rut="55555555-5", password="clave-segura-123")
        cls.otro_entrenador.groups.add(grupo)
        PerfilEntrenador.objects.create(usuario=cls.otro_entrenador).categorias.add(cls.u13)
 
        cls.secretaria = Usuario.objects.create_user(rut="22222222-2", password="clave-segura-123")
        cls.secretaria.groups.add(Group.objects.get_or_create(name="Administración")[0])
 
    def datos(self, **cambios):
        base = {
            "categoria_id": self.u15.pk,
            "nombre": "Técnico",
            "fecha": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "hora_inicio": "18:30",
            "duracion": 90,
            "objetivo": "Defensa en zona",
            "responsable_id": self.entrenador.pk,
        }
        base.update(cambios)
        return base
 
    def crear(self, fecha=None):
        return Entrenamiento.objects.create(
            categoria=self.u15, nombre="Técnico", duracion=90,
            fecha=fecha or timezone.localdate() + timedelta(days=2),
            hora_inicio="18:30", objetivo="Defensa en zona",
            responsable=self.entrenador, creado_por=self.entrenador,
        )
 
    def test_planifica_con_fecha_hora_objetivo_y_responsable(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:entrenamientos"), self.datos(responsable_id=self.ayudante.pk))
        e = Entrenamiento.objects.get()
        self.assertEqual(e.hora_inicio.strftime("%H:%M"), "18:30")
        self.assertEqual(e.objetivo, "Defensa en zona")
        self.assertEqual(e.responsable, self.ayudante)
 
    def test_objetivo_hora_y_responsable_son_obligatorios(self):
        self.client.force_login(self.entrenador)
        for campo in ["objetivo", "hora_inicio", "responsable_id"]:
            self.client.post(reverse("deportivo:entrenamientos"), self.datos(**{campo: ""}))
        self.assertFalse(Entrenamiento.objects.exists())
 
    def test_responsable_debe_ser_de_la_categoria(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:entrenamientos"), self.datos(responsable_id=self.otro_entrenador.pk))
        self.assertFalse(Entrenamiento.objects.exists())
 
    def test_crear_queda_en_el_historial(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:entrenamientos"), self.datos())
        e = Entrenamiento.objects.get()
        self.assertTrue(Auditoria.objects.filter(
            accion="PLANIFICACION_CREADA", entidad_id=e.pk,
        ).exists())
 
    def test_editar_guarda_antes_y_despues(self):
        e = self.crear()
        self.client.force_login(self.entrenador)
        self.client.post(
            reverse("deportivo:editar_planificacion", args=[e.pk]),
            self.datos(objetivo="Tiro libre", hora_inicio="19:00"),
        )
        e.refresh_from_db()
        self.assertEqual(e.objetivo, "Tiro libre")
 
        registro = Auditoria.objects.get(accion="PLANIFICACION_MODIFICADA", entidad_id=e.pk)
        self.assertEqual(registro.detalle["objetivo"], {"antes": "Defensa en zona", "despues": "Tiro libre"})
        self.assertEqual(registro.detalle["hora_inicio"], {"antes": "18:30", "despues": "19:00"})
        self.assertEqual(registro.usuario, self.entrenador)
 
    def test_historial_se_ve_en_pantalla(self):
        e = self.crear()
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:editar_planificacion", args=[e.pk]), self.datos(objetivo="Tiro libre"))
        respuesta = self.client.get(reverse("deportivo:editar_planificacion", args=[e.pk]))
        self.assertContains(respuesta, "Tiro libre")
        self.assertContains(respuesta, "Defensa en zona")
 
    def test_entrenador_no_edita_entrenamiento_pasado(self):
        e = self.crear(fecha=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:editar_planificacion", args=[e.pk]), self.datos(objetivo="Cambio"))
        e.refresh_from_db()
        self.assertEqual(e.objetivo, "Defensa en zona")
 
    def test_administracion_si_corrige_entrenamiento_pasado(self):
        e = self.crear(fecha=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.secretaria)
        self.client.post(
            reverse("deportivo:editar_planificacion", args=[e.pk]),
            self.datos(objetivo="Corregido", fecha=e.fecha.isoformat()),
        )
        e.refresh_from_db()
        self.assertEqual(e.objetivo, "Corregido")
 
    def test_entrenador_no_ve_planificacion_de_otra_categoria(self):
        e = self.crear()
        self.client.force_login(self.otro_entrenador)
        respuesta = self.client.get(reverse("deportivo:editar_planificacion", args=[e.pk]))
        self.assertEqual(respuesta.status_code, 404)
 
    def test_entrenamiento_con_asistencia_no_se_puede_borrar(self):
        from django.db.models import ProtectedError
        from usuarios.models import Jugador
 
        e = self.crear(fecha=timezone.localdate())
        jugador = Jugador.objects.create(
            rut="22333444-K", nombres="Tomas", apellidos="Vergara",
            fecha_nacimiento=date(2012, 2, 1), rama=Categoria.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO, categoria_actual=self.u15,
        )
        Asistencia.objects.create(entrenamiento=e, jugador=jugador, estado="PRESENTE", registrado_por=self.entrenador)
        with self.assertRaises(ProtectedError):
            e.delete()

class CalendarioTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", verbosity=0)
        Usuario = get_user_model()

        cls.u15 = Categoria.objects.get(nombre="U15 Varones")
        cls.u13 = Categoria.objects.get(nombre="U13 Damas")

        cls.entrenador = Usuario.objects.create_user(rut="33333333-3", password="clave-segura-123")
        cls.entrenador.groups.add(Group.objects.get_or_create(name="Entrenador")[0])
        PerfilEntrenador.objects.create(usuario=cls.entrenador).categorias.add(cls.u15)

        cls.secretaria = Usuario.objects.create_user(rut="22222222-2", password="clave-segura-123")
        cls.secretaria.groups.add(Group.objects.get_or_create(name="Administración")[0])

        # Apoderada de Tomás (U15)
        cls.mama = Usuario.objects.create_user(rut="12345678-5", password="clave-segura-123")
        apoderada = Apoderado.objects.create(
            usuario=cls.mama, rut="12345678-5", nombres="Patricia",
            apellidos="Vergara", telefono="+56911111111",
        )
        tomas = Jugador.objects.create(
            rut="22333444-K", nombres="Tomas", apellidos="Vergara",
            fecha_nacimiento=date(2012, 2, 1), rama=Categoria.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO, categoria_actual=cls.u15,
        )
        ApoderadoJugador.objects.create(
            apoderado=apoderada, jugador=tomas, parentesco="MADRE", es_principal=True,
        )

        cls.otro = Usuario.objects.create_user(rut="11111111-1", password="clave-segura-123")

    def evento(self, categoria=None, dias=3, titulo="Partido"):
        return Evento.objects.create(
            tipo=Evento.Tipo.PARTIDO, titulo=titulo, categoria=categoria,
            fecha=timezone.localdate() + timedelta(days=dias), hora="10:00",
            lugar="Gimnasio Epicentro", creado_por=self.secretaria,
        )

    def datos(self, **cambios):
        base = {
            "tipo": "PARTIDO",
            "titulo": "Ayllu vs Arica",
            "categoria_id": self.u15.pk,
            "fecha": (timezone.localdate() + timedelta(days=5)).isoformat(),
            "hora": "11:00",
            "lugar": "Gimnasio Epicentro",
            "descripcion": "",
        }
        base.update(cambios)
        return base

    # ---------- consultar ----------

    def test_panel_muestra_acceso_al_calendario(self):
        self.client.force_login(self.mama)
        respuesta = self.client.get(reverse("panel"))
        self.assertContains(respuesta, reverse("deportivo:calendario"))

    def test_apoderada_ve_eventos_de_su_categoria_y_del_club(self):
        self.evento(self.u15, titulo="Partido U15")
        self.evento(None, titulo="Aniversario del club")
        self.evento(self.u13, titulo="Partido U13")

        self.client.force_login(self.mama)
        respuesta = self.client.get(reverse("deportivo:calendario"))

        self.assertContains(respuesta, "Partido U15")
        self.assertContains(respuesta, "Aniversario del club")
        self.assertContains(respuesta, "Gimnasio Epicentro")
        self.assertNotContains(respuesta, "Partido U13")

    def test_no_muestra_eventos_pasados(self):
        self.evento(self.u15, dias=-1, titulo="Partido de ayer")
        self.client.force_login(self.mama)
        respuesta = self.client.get(reverse("deportivo:calendario"))
        self.assertNotContains(respuesta, "Partido de ayer")

    def test_filtro_por_categoria(self):
        self.evento(self.u15, titulo="Partido U15")
        self.evento(self.u13, titulo="Partido U13")

        self.client.force_login(self.secretaria)
        respuesta = self.client.get(reverse("deportivo:calendario"), {"categoria": self.u13.pk})

        self.assertContains(respuesta, "Partido U13")
        self.assertNotContains(respuesta, "Partido U15")

    def test_usuario_sin_perfil_solo_ve_eventos_del_club(self):
        self.evento(self.u15, titulo="Partido U15")
        self.evento(None, titulo="Aniversario del club")

        self.client.force_login(self.otro)
        respuesta = self.client.get(reverse("deportivo:calendario"))

        self.assertContains(respuesta, "Aniversario del club")
        self.assertNotContains(respuesta, "Partido U15")

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get(reverse("deportivo:calendario"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse("login"), respuesta.url)

    # ---------- publicar ----------

    def test_entrenador_publica_evento_de_su_categoria(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:calendario"), self.datos())

        evento = Evento.objects.get()
        self.assertEqual(evento.categoria, self.u15)
        self.assertEqual(evento.creado_por, self.entrenador)
        self.assertTrue(Auditoria.objects.filter(accion="EVENTO_CREADO", entidad_id=evento.pk).exists())

    def test_entrenador_no_publica_en_categoria_ajena(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:calendario"), self.datos(categoria_id=self.u13.pk))
        self.assertFalse(Evento.objects.exists())

    def test_entrenador_no_publica_para_todo_el_club(self):
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:calendario"), self.datos(categoria_id=""))
        self.assertFalse(Evento.objects.exists())

    def test_administracion_publica_para_todo_el_club(self):
        self.client.force_login(self.secretaria)
        self.client.post(reverse("deportivo:calendario"), self.datos(categoria_id="", tipo="CLUB"))
        evento = Evento.objects.get()
        self.assertIsNone(evento.categoria)

    def test_apoderada_no_puede_publicar(self):
        self.client.force_login(self.mama)
        self.client.post(reverse("deportivo:calendario"), self.datos())
        self.assertFalse(Evento.objects.exists())

    def test_no_publica_con_datos_vacios(self):
        self.client.force_login(self.secretaria)
        self.client.post(reverse("deportivo:calendario"), self.datos(titulo="", lugar="", hora="", fecha=""))
        self.assertFalse(Evento.objects.exists())

    def test_no_publica_en_fecha_pasada(self):
        self.client.force_login(self.secretaria)
        ayer = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.client.post(reverse("deportivo:calendario"), self.datos(fecha=ayer))
        self.assertFalse(Evento.objects.exists())

    # ---------- eliminar ----------

    def test_entrenador_no_elimina_evento_de_otro(self):
        evento = self.evento(self.u15)  # lo creó la secretaria
        self.client.force_login(self.entrenador)
        self.client.post(reverse("deportivo:eliminar_evento", args=[evento.pk]))
        self.assertTrue(Evento.objects.filter(pk=evento.pk).exists())

    def test_administracion_elimina_y_queda_auditoria(self):
        evento = self.evento(self.u15)
        self.client.force_login(self.secretaria)
        self.client.post(reverse("deportivo:eliminar_evento", args=[evento.pk]))
        self.assertFalse(Evento.objects.filter(pk=evento.pk).exists())
        self.assertTrue(Auditoria.objects.filter(accion="EVENTO_ELIMINADO", entidad_id=evento.pk).exists())