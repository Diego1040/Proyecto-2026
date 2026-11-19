from datetime import date, timedelta

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from deportivo.models import Asistencia, Entrenamiento, PerfilEntrenador
from .models import AlertaSalud, Apoderado, ApoderadoJugador, Categoria, HistorialCategoria, Jugador, SolicitudInscripcion, Usuario

TEMPORADA = 2026


class PerfilesBloque13Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_categorias", temporada=TEMPORADA, verbosity=0)

        cls.usuario_apoderado = Usuario.objects.create_user(
            rut="20347119-K",
        )
        cls.apoderado = Apoderado.objects.create(
            usuario=cls.usuario_apoderado,
            rut="20347119-K",
            nombres="Ana",
            apellidos="Apoderada",
            telefono="+56911111111",
            email="ana@example.com",
        )
        cls.jugador_vinculado = Jugador.objects.create(
            rut="11111111-1",
            nombres="Jugador",
            apellidos="Visible",
            fecha_nacimiento=date(2012, 3, 10),
            rama=Jugador.Rama.DAMAS,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        ApoderadoJugador.objects.create(
            apoderado=cls.apoderado,
            jugador=cls.jugador_vinculado,
            parentesco="MADRE",
            es_principal=True,
        )

        cls.jugador_inactivo = Jugador.objects.create(
            rut="33333333-3",
            nombres="Jugador",
            apellidos="Oculto",
            fecha_nacimiento=date(2013, 3, 10),
            rama=Jugador.Rama.VARONES,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        ApoderadoJugador.objects.create(
            apoderado=cls.apoderado,
            jugador=cls.jugador_inactivo,
            parentesco="TUTOR",
            activo=False,
        )

        cls.usuario_jugador = Usuario.objects.create_user(
            rut="12345678-5",
        )
        cls.jugador_con_cuenta = Jugador.objects.create(
            usuario=cls.usuario_jugador,
            rut="12345678-5",
            nombres="Perfil",
            apellidos="Jugador",
            fecha_nacimiento=date(1990, 4, 20),
            rama=Jugador.Rama.DAMAS,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )
        AlertaSalud.objects.create(
            jugador=cls.jugador_con_cuenta,
            tipo="Alergia",
            descripcion="Alerta visible",
        )
        AlertaSalud.objects.create(
            jugador=cls.jugador_con_cuenta,
            tipo="Antecedente",
            descripcion="Alerta inactiva",
            activa=False,
        )
        categoria = Categoria.objects.get(nombre="Todo Competidor Damas")
        HistorialCategoria.objects.create(
            jugador=cls.jugador_con_cuenta,
            categoria_nueva=categoria,
            tipo_cambio=HistorialCategoria.TipoCambio.AUTOMATICO,
        )

    def test_panel_muestra_opciones_segun_perfil(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("panel"))

        self.assertContains(respuesta, reverse("perfil_apoderado"))
        self.assertNotContains(respuesta, reverse("perfil_jugador"))

    def test_perfil_jugador_muestra_solo_alertas_activas_e_historial(self):
        self.client.force_login(self.usuario_jugador)
        respuesta = self.client.get(reverse("perfil_jugador"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Perfil Jugador")
        self.assertContains(respuesta, "Alerta visible")
        self.assertNotContains(respuesta, "Alerta inactiva")
        self.assertContains(respuesta, "Todo Competidor Damas")

    def test_perfil_apoderado_muestra_solo_vinculos_activos(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("perfil_apoderado"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Jugador Visible")
        self.assertNotContains(respuesta, "Jugador Oculto")
        self.assertNotContains(respuesta, "Permiso de gestión")
        self.assertNotContains(respuesta, "Habilitado")
        self.assertNotContains(respuesta, "Solo consulta")
        self.assertTrue(self.apoderado.vinculos_jugadores.get(activo=True).puede_gestionar)

    def test_perfil_apoderado_muestra_solo_consulta_sin_cambiar_permiso(self):
        vinculo = self.apoderado.vinculos_jugadores.get(activo=True)
        vinculo.puede_gestionar = False
        vinculo.save(update_fields=["puede_gestionar"])
        self.client.force_login(self.usuario_apoderado)

        respuesta = self.client.get(reverse("perfil_apoderado"))

        self.assertContains(respuesta, "Solo consulta")
        self.assertNotContains(respuesta, "Permiso de gestión")
        vinculo.refresh_from_db()
        self.assertFalse(vinculo.puede_gestionar)

    def test_perfiles_rechazan_una_cuenta_sin_el_perfil_requerido(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.get(reverse("perfil_jugador"))

        self.assertRedirects(respuesta, reverse("panel"))

    def test_jugador_actualiza_unicamente_su_telefono(self):
        self.client.force_login(self.usuario_jugador)

        respuesta = self.client.post(
            reverse("perfil_jugador"),
            {
                "telefono": "+56987654321",
                "rut": "22222222-2",
                "nombres": "Nombre alterado",
                "apellidos": "Apellido alterado",
                "estado": Jugador.Estado.INACTIVO,
                "procedencia": Jugador.Procedencia.OTRO_CLUB,
            },
        )

        self.assertRedirects(respuesta, reverse("perfil_jugador"))

        jugador = Jugador.objects.get(pk=self.jugador_con_cuenta.pk)
        self.assertEqual(jugador.telefono, "+56987654321")
        self.assertEqual(jugador.rut, "12345678-5")
        self.assertEqual(jugador.nombres, "Perfil")
        self.assertEqual(jugador.apellidos, "Jugador")
        self.assertEqual(jugador.estado, Jugador.Estado.PENDIENTE)
        self.assertEqual(
            jugador.procedencia,
            Jugador.Procedencia.INDEPENDIENTE,
        )

    def test_usuario_no_puede_editar_el_contacto_de_otro_perfil(self):
        telefono_original = Apoderado.objects.get(
            pk=self.apoderado.pk,
        ).telefono
        self.client.force_login(self.usuario_jugador)

        respuesta = self.client.post(
            reverse("perfil_apoderado"),
            {
                "telefono": "+56900000000",
                "apoderado_id": self.apoderado.pk,
            },
        )

        self.assertRedirects(respuesta, reverse("panel"))
        telefono_actual = Apoderado.objects.get(
            pk=self.apoderado.pk,
        ).telefono
        self.assertEqual(telefono_actual, telefono_original)

    def test_panel_conserva_todas_las_capacidades_y_no_modifica_vinculos(self):
        usuario = self.usuario_apoderado
        Jugador.objects.create(
            usuario=usuario, rut=usuario.rut, nombres="Ana", apellidos="Deportista",
            fecha_nacimiento=date(1990, 3, 10), rama="DAMAS",
        )
        usuario.groups.add(
            Group.objects.get_or_create(name="Administración")[0],
            Group.objects.get_or_create(name="Entrenador")[0],
        )
        perfil = PerfilEntrenador.objects.create(usuario=usuario)
        perfil.categorias.add(Categoria.objects.get(nombre="U15 Damas"))
        self.client.force_login(usuario)
        anterior = list(ApoderadoJugador.objects.order_by("pk").values())
        respuesta = self.client.get(reverse("panel"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["perfiles"], ["Jugador", "Apoderado", "Administración", "Entrenador"])
        for nombre in ("perfil_jugador", "perfil_apoderado", "solicitudes_administracion",
                       "categorias_jugadores", "deportivo:entrenamientos"):
            self.assertContains(respuesta, reverse(nombre))
        self.client.get(reverse("perfil_jugador"))
        self.client.get(reverse("perfil_apoderado"))
        self.assertContains(self.client.get(reverse("deportivo:entrenamientos")), reverse("panel"))
        self.assertContains(self.client.get(reverse("categorias_jugadores")), reverse("panel"))
        self.assertEqual(list(ApoderadoJugador.objects.order_by("pk").values()), anterior)

    def test_staff_solo_tiene_acceso_tecnico_y_no_administracion_del_club(self):
        usuario = Usuario.objects.create_user(rut="22222222-2", is_staff=True)
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("panel"))
        self.assertContains(respuesta, reverse("admin:index"))
        self.assertNotContains(respuesta, reverse("solicitudes_administracion"))
        self.assertNotContains(respuesta, reverse("categorias_jugadores"))
        self.assertNotContains(respuesta, reverse("deportivo:entrenamientos"))
        self.assertEqual(respuesta.context["perfiles"], [])

    def test_administracion_sin_staff_conserva_acceso_deportivo(self):
        usuario = Usuario.objects.create_user(rut="22222222-2")
        usuario.groups.add(Group.objects.get_or_create(name="Administración")[0])
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("panel"))
        self.assertEqual(respuesta.context["perfiles"], ["Administración"])
        self.assertFalse(respuesta.context["es_entrenador"])
        for nombre in ("solicitudes_administracion", "categorias_jugadores", "deportivo:entrenamientos"):
            self.assertContains(respuesta, reverse(nombre))
        self.assertNotContains(respuesta, reverse("admin:index"))

    def test_apoderado_con_varios_jugadores_ve_asistencia_y_solicitudes_sin_salud(self):
        adulto = Jugador.objects.create(
            rut="22222222-2", nombres="Adulto", apellidos="Vinculado",
            fecha_nacimiento=date(1990, 3, 10), rama="VARONES",
        )
        ApoderadoJugador.objects.create(
            apoderado=self.apoderado, jugador=adulto, parentesco="TUTOR",
            es_principal=True, puede_gestionar=False,
        )
        for jugador, estados in ((self.jugador_vinculado, ("PRESENTE", "AUSENTE")),
                                 (adulto, ("JUSTIFICADO",))):
            for estado in estados:
                entrenamiento = Entrenamiento.objects.create(
                    categoria=Categoria.objects.get(nombre="U15 Damas"),
                    nombre="Técnico", duracion=90, fecha=timezone.localdate(),
                    creado_por=self.usuario_apoderado,
                )
                Asistencia.objects.create(
                    entrenamiento=entrenamiento, jugador=jugador,
                    estado=estado, registrado_por=self.usuario_apoderado,
                )
        anterior = Entrenamiento.objects.create(
            categoria=Categoria.objects.get(nombre="U15 Damas"), nombre="Mes anterior",
            duracion=90, fecha=timezone.localdate().replace(day=1) - timedelta(days=1),
            creado_por=self.usuario_apoderado,
        )
        Asistencia.objects.create(entrenamiento=anterior, jugador=adulto, estado="PRESENTE",
                                  registrado_por=self.usuario_apoderado)
        SolicitudInscripcion.objects.create(
            jugador=self.jugador_vinculado, consentimiento=True,
            estado=SolicitudInscripcion.Estado.RECHAZADA, motivo_rechazo="Falta documentación",
        )
        SolicitudInscripcion.objects.create(jugador=adulto, consentimiento=True)
        AlertaSalud.objects.create(jugador=adulto, tipo="DatoPrivado", descripcion="SaludReservada")
        self.client.force_login(self.usuario_apoderado)
        relaciones = list(ApoderadoJugador.objects.order_by("pk").values())
        respuesta = self.client.get(reverse("perfil_apoderado"))
        vinculos = {v.jugador_id: v for v in respuesta.context["vinculos"]}
        self.assertEqual(set(vinculos), {adulto.pk, self.jugador_vinculado.pk})
        self.assertEqual(vinculos[self.jugador_vinculado.pk].jugador.asistencia_mes["porcentaje"], 50)
        self.assertEqual(vinculos[adulto.pk].jugador.asistencia_mes["total"], 1)
        self.assertEqual(vinculos[adulto.pk].jugador.asistencia_mes["justificadas"], 1)
        for texto in ("50%", "Justificadas", "Rechazada", "Pendiente", "Falta documentación",
                      "Solo consulta", "Adulto Vinculado"):
            self.assertContains(respuesta, texto)
        for texto in ("Jugador Oculto", "DatoPrivado", "SaludReservada"):
            self.assertNotContains(respuesta, texto)
        self.assertEqual(list(ApoderadoJugador.objects.order_by("pk").values()), relaciones)

    def test_contacto_del_perfil_sincroniza_correos_y_no_edita_identidad_ajena(self):
        self.client.force_login(self.usuario_apoderado)
        respuesta = self.client.post(reverse("perfil_apoderado"), {
            "telefono": "+56912345678", "email": "nuevo@example.com",
            "rut": self.usuario_jugador.rut, "apoderado_id": self.jugador_con_cuenta.pk,
            "usuario_id": self.usuario_jugador.pk, "nombres": "Alterado",
        })
        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        self.apoderado.refresh_from_db()
        self.usuario_apoderado.refresh_from_db()
        self.usuario_jugador.refresh_from_db()
        self.assertEqual(self.apoderado.telefono, "+56912345678")
        self.assertEqual(self.apoderado.email, "nuevo@example.com")
        self.assertEqual(self.usuario_apoderado.email, self.apoderado.email)
        self.assertEqual(self.apoderado.rut, "20347119-K")
        self.assertEqual(self.apoderado.nombres, "Ana")
        self.assertEqual(self.usuario_jugador.email, "")

    def test_correo_invalido_no_actualiza_contacto(self):
        self.client.force_login(self.usuario_apoderado)
        anterior = Apoderado.objects.values().get(pk=self.apoderado.pk)
        respuesta = self.client.post(reverse("perfil_apoderado"), {
            "telefono": "+56999999999", "email": "invalido",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("email", respuesta.context["contacto_form"].errors)
        self.assertEqual(Apoderado.objects.values().get(pk=self.apoderado.pk), anterior)

    def test_cambio_correo_apoderado_permite_aprobar_solicitud_del_mismo_jugador(self):
        usuario = self.usuario_apoderado
        usuario.email = self.apoderado.email
        usuario.set_password("ClaveExistenteMuySegura123!")
        usuario.save(update_fields=["email", "password"])
        jugador = Jugador.objects.create(
            usuario=usuario, rut=usuario.rut, nombres="Ana", apellidos="Apoderada",
            fecha_nacimiento=date(1990, 3, 10), rama="DAMAS", email=usuario.email,
            categoria_actual=Categoria.objects.get(nombre="Todo Competidor Damas"),
        )
        self.assertTrue(usuario.is_active)
        self.assertEqual(jugador.email, self.apoderado.email)
        anterior = Jugador.objects.values().get(pk=jugador.pk)
        relaciones = list(ApoderadoJugador.objects.order_by("pk").values())
        self.client.force_login(usuario)

        respuesta = self.client.post(reverse("perfil_apoderado"), {
            "telefono": self.apoderado.telefono, "email": "nuevo@example.com",
        })
        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        usuario.refresh_from_db()
        self.apoderado.refresh_from_db()
        jugador.refresh_from_db()
        self.assertEqual(usuario.email, "nuevo@example.com")
        self.assertEqual(self.apoderado.email, usuario.email)
        self.assertEqual(jugador.email, usuario.email)
        anterior["email"] = "nuevo@example.com"
        self.assertEqual(Jugador.objects.values().get(pk=jugador.pk), anterior)
        self.assertEqual(usuario.rut, "20347119-K")
        self.assertEqual(self.apoderado.rut, usuario.rut)
        self.assertEqual(list(ApoderadoJugador.objects.order_by("pk").values()), relaciones)

        solicitud = SolicitudInscripcion.objects.create(
            jugador=jugador, solicitante=usuario, procedencia=jugador.procedencia, consentimiento=True,
        )
        actor = Usuario.objects.create_user(rut="22222222-2")
        actor.groups.add(Group.objects.get_or_create(name="Administración")[0])
        self.client.force_login(actor)
        detalle = reverse("solicitud_detalle", args=[solicitud.pk])
        respuesta = self.client.post(reverse("solicitud_iniciar_revision", args=[solicitud.pk]))
        self.assertRedirects(respuesta, detalle)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.EN_REVISION)

        respuesta = self.client.post(reverse("solicitud_aprobar", args=[solicitud.pk]))
        self.assertRedirects(respuesta, detalle)
        solicitud.refresh_from_db()
        jugador.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudInscripcion.Estado.APROBADA)
        self.assertEqual(solicitud.usuario_autorizado_id, usuario.pk)
        self.assertEqual(jugador.usuario_id, usuario.pk)
        self.assertEqual(jugador.estado, Jugador.Estado.ACTIVO)
        self.assertEqual(list(ApoderadoJugador.objects.order_by("pk").values()), relaciones)

    def test_contacto_apoderado_conserva_correo_distinto_del_jugador(self):
        usuario = self.usuario_apoderado
        usuario.email = self.apoderado.email
        usuario.save(update_fields=["email"])
        jugador = Jugador.objects.create(
            usuario=usuario, rut=usuario.rut, nombres="Ana", apellidos="Apoderada",
            fecha_nacimiento=date(1990, 3, 10), rama="DAMAS", email="deportivo@example.com",
        )
        anterior = Jugador.objects.values().get(pk=jugador.pk)
        self.client.force_login(usuario)
        respuesta = self.client.post(reverse("perfil_apoderado"), {
            "telefono": self.apoderado.telefono, "email": "nuevo@example.com",
        })
        self.assertRedirects(respuesta, reverse("perfil_apoderado"))
        usuario.refresh_from_db()
        self.apoderado.refresh_from_db()
        self.assertEqual(usuario.email, "nuevo@example.com")
        self.assertEqual(self.apoderado.email, usuario.email)
        self.assertEqual(Jugador.objects.values().get(pk=jugador.pk), anterior)

    def test_perfil_jugador_ignora_identificadores_ajenos_y_no_expone_datos_administrativos(self):
        self.client.force_login(self.usuario_jugador)
        respuesta = self.client.get(reverse("perfil_jugador"), {"jugador_id": self.jugador_vinculado.pk})
        self.assertEqual(respuesta.context["jugador"].pk, self.jugador_con_cuenta.pk)
        self.assertNotContains(respuesta, "Jugador Visible")
        self.assertNotContains(respuesta, reverse("solicitudes_administracion"))

    def test_perfiles_exigen_sesion_y_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        for nombre in ("perfil_jugador", "perfil_apoderado"):
            self.assertEqual(cliente.get(reverse(nombre)).status_code, 302)
        for usuario, nombre in ((self.usuario_jugador, "perfil_jugador"),
                                (self.usuario_apoderado, "perfil_apoderado")):
            cliente.force_login(usuario)
            self.assertEqual(cliente.post(reverse(nombre), {"telefono": "1"}).status_code, 403)
