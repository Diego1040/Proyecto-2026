"""Migración desde Miguel sin perder identidades ni relaciones deportivas."""
from datetime import date

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from deportivo.models import Asistencia, Entrenamiento, PerfilEntrenador

from .models import (
    Apoderado, ApoderadoJugador, Auditoria, Categoria, HistorialCategoria,
    Jugador, ReglaCategoria, SolicitudInscripcion, Usuario,
)
from .services import asignar_categoria_automatica, obtener_categoria_automatica


class MigracionesFundacionTest(TransactionTestCase):
    desde = [
        ("usuarios", "0008_auditoria"),
        ("deportivo", "0003_alter_entrenamiento_options"),
    ]
    hasta = [
        ("usuarios", "0012_normalizar_ruts_y_categorias_adultas"),
        ("deportivo", "0003_alter_entrenamiento_options"),
    ]

    def setUp(self):
        super().setUp()
        self.addCleanup(self.migrar)
        executor = MigrationExecutor(connection)
        executor.migrate(self.desde)
        self.apps_antiguas = executor.loader.project_state(self.desde).apps

    def migrar(self):
        MigrationExecutor(connection).migrate(self.hasta)

    def _crear_jugador_antiguo(self, rut, **datos):
        datos_jugador = {
            "nombres": "Alex", "apellidos": "Jugador",
            "fecha_nacimiento": date(1990, 3, 10), "rama": "VARONES",
        }
        datos_jugador.update(datos)
        modelo = self.apps_antiguas.get_model("usuarios", "Jugador")
        return modelo.objects.create(rut=rut, **datos_jugador)

    def _crear_apoderado_antiguo(self, rut, **datos):
        datos_apoderado = {"nombres": "Alex", "apellidos": "Apoderado", "telefono": "123"}
        datos_apoderado.update(datos)
        modelo = self.apps_antiguas.get_model("usuarios", "Apoderado")
        return modelo.objects.create(rut=rut, **datos_apoderado)

    def test_desde_miguel_conserva_cuentas_historial_y_deportivo(self):
        UsuarioAntiguo = self.apps_antiguas.get_model("usuarios", "Usuario")
        CategoriaAntigua = self.apps_antiguas.get_model("usuarios", "Categoria")
        ReglaAntigua = self.apps_antiguas.get_model("usuarios", "ReglaCategoria")
        HistorialAntiguo = self.apps_antiguas.get_model("usuarios", "HistorialCategoria")
        clave = make_password("ClaveHistoricaSegura123!")
        cuenta = UsuarioAntiguo.objects.create(
            rut="011111111-1", email="cuenta@example.com", password=clave,
        )
        grupo = self.apps_antiguas.get_model("auth", "Group").objects.create(
            name="Administración",
        )
        cuenta.groups.add(grupo)
        suspendida = UsuarioAntiguo.objects.create(
            rut="22222222-2", email="suspendida@example.com",
            password=clave, is_active=False,
        )
        sin_clave = UsuarioAntiguo.objects.create(
            rut="33333333-3", password=make_password(None),
        )
        damas = CategoriaAntigua.objects.create(
            nombre="T/C Damas", rama="DAMAS", orden=10,
        )
        varones = CategoriaAntigua.objects.create(
            nombre="T/C Varones", rama="VARONES", orden=11,
        )
        u17 = CategoriaAntigua.objects.create(nombre="U17 Damas", rama="DAMAS", orden=8)
        ReglaAntigua.objects.create(categoria=damas, temporada=2026, edad_min=18)
        ReglaAntigua.objects.create(categoria=damas, temporada=2025, edad_min=18)
        ReglaAntigua.objects.create(categoria=varones, temporada=2026, edad_min=18)
        adulto = self._crear_jugador_antiguo(
            rut="11111111-1", usuario=cuenta, apellidos="Adulto",
            categoria_actual=varones, estado="ACTIVO",
        )
        apoderado = self._crear_apoderado_antiguo(
            rut="011111111-1", usuario=cuenta, apellidos="Adulto",
            telefono="+56911111111",
        )
        jugadora = self._crear_jugador_antiguo(
            rut="023456789-6", nombres="Ana", apellidos="Jugadora",
            rama="DAMAS", categoria_actual=damas, estado="ACTIVO",
        )
        vinculo = self.apps_antiguas.get_model("usuarios", "ApoderadoJugador").objects.create(
            apoderado=apoderado, jugador=jugadora, parentesco="Tutor", es_principal=True,
        )
        anterior = HistorialAntiguo.objects.create(
            jugador=jugadora, categoria_anterior=damas, categoria_nueva=u17,
            tipo_cambio="AUTOMATICO",
        )
        excepcion = HistorialAntiguo.objects.create(
            jugador=jugadora, categoria_anterior=u17, categoria_nueva=damas,
            tipo_cambio="EXCEPCION_MANUAL", cambiado_por=cuenta, motivo="Autorización histórica",
        )
        auditoria = self.apps_antiguas.get_model("usuarios", "Auditoria").objects.create(
            usuario=cuenta, accion="CATEGORIA_EXCEPCION_MANUAL", entidad="Jugador",
            entidad_id=jugadora.pk, detalle={"categoria_nueva": "T/C Damas"},
        )
        solicitud = self.apps_antiguas.get_model("usuarios", "SolicitudInscripcion").objects.create(
            jugador=jugadora, solicitante=cuenta, procedencia="INDEPENDIENTE",
            consentimiento=True, estado="APROBADA", revisado_por=cuenta,
            fecha_revision=timezone.now(),
        )
        entrenamiento = self.apps_antiguas.get_model("deportivo", "Entrenamiento").objects.create(
            categoria=damas, nombre="Histórico", duracion=60,
            fecha=date(2026, 9, 1), creado_por=cuenta,
        )
        asistencia = self.apps_antiguas.get_model("deportivo", "Asistencia").objects.create(
            entrenamiento=entrenamiento, jugador=jugadora,
            estado="PRESENTE", registrado_por=cuenta,
        )
        entrenador = self.apps_antiguas.get_model("deportivo", "PerfilEntrenador").objects.create(
            usuario=cuenta,
        )
        entrenador.categorias.add(damas, varones)
        historial_original = list(HistorialAntiguo.objects.order_by("pk").values())
        reglas_originales = list(ReglaAntigua.objects.order_by("pk").values())
        asignaciones_originales = list(
            entrenador.categorias.through.objects.order_by("pk").values(),
        )
        entrenamiento_original = Entrenamiento.objects.filter(pk=entrenamiento.pk).values().get()
        asistencia_original = Asistencia.objects.filter(pk=asistencia.pk).values().get()

        self.migrar()

        cuenta_nueva = Usuario.objects.get(pk=cuenta.pk)
        self.assertEqual(cuenta_nueva.rut, "11111111-1")
        self.assertEqual(cuenta_nueva.password, clave)
        self.assertTrue(cuenta_nueva.is_active)
        self.assertFalse(cuenta_nueva.is_staff)
        self.assertEqual(list(cuenta_nueva.groups.values_list("pk", flat=True)), [grupo.pk])
        self.assertIsNotNone(cuenta_nueva.activado_en)
        self.assertIsNone(Usuario.objects.get(pk=suspendida.pk).activado_en)
        self.assertFalse(Usuario.objects.get(pk=suspendida.pk).is_active)
        self.assertIsNone(Usuario.objects.get(pk=sin_clave.pk).activado_en)
        jugador_nuevo = Jugador.objects.get(pk=adulto.pk)
        apoderado_nuevo = Apoderado.objects.get(pk=apoderado.pk)
        self.assertEqual(jugador_nuevo.usuario_id, cuenta.pk)
        self.assertEqual(apoderado_nuevo.usuario_id, cuenta.pk)
        self.assertEqual(apoderado_nuevo.rut, "11111111-1")
        self.assertEqual(jugador_nuevo.email, cuenta.email)
        self.assertEqual(apoderado_nuevo.email, cuenta.email)
        self.assertEqual(jugador_nuevo.nombre_contacto_emergencia, "")
        self.assertEqual(jugador_nuevo.telefono_contacto_emergencia, "")
        jugador_nuevo.full_clean()
        apoderado_nuevo.full_clean()
        self.assertEqual(Categoria.objects.get(pk=varones.pk).nombre, "Todo Competidor Varones")
        self.assertEqual(Categoria.objects.get(pk=damas.pk).nombre, "Todo Competidor Damas")
        self.assertEqual(jugador_nuevo.categoria_actual_id, varones.pk)
        self.assertEqual(Jugador.objects.get(pk=jugadora.pk).categoria_actual_id, damas.pk)
        self.assertTrue(Categoria.objects.get(pk=damas.pk).activa)
        self.assertEqual(list(ReglaCategoria.objects.order_by("pk").values()), reglas_originales)
        self.assertEqual(list(HistorialCategoria.objects.order_by("pk").values()), historial_original)
        self.assertEqual(HistorialCategoria.objects.get(pk=anterior.pk).categoria_anterior_id, damas.pk)
        self.assertEqual(HistorialCategoria.objects.get(pk=excepcion.pk).categoria_nueva_id, damas.pk)
        self.assertEqual(Auditoria.objects.get(pk=auditoria.pk).detalle, auditoria.detalle)
        self.assertEqual(ApoderadoJugador.objects.get(pk=vinculo.pk).jugador_id, jugadora.pk)
        solicitud_nueva = SolicitudInscripcion.objects.get(pk=solicitud.pk)
        self.assertEqual(solicitud_nueva.estado, "APROBADA")
        self.assertIsNone(solicitud_nueva.usuario_autorizado_id)
        self.assertEqual(Entrenamiento.objects.filter(pk=entrenamiento.pk).values().get(), entrenamiento_original)
        self.assertEqual(Asistencia.objects.filter(pk=asistencia.pk).values().get(), asistencia_original)
        self.assertEqual(Asistencia.objects.get(pk=asistencia.pk).jugador_id, jugadora.pk)
        self.assertEqual(list(PerfilEntrenador.categorias.through.objects.order_by("pk").values()),
                         asignaciones_originales)
        self.assertEqual(set(PerfilEntrenador.objects.get(pk=entrenador.pk).categorias.values_list(
            "pk", flat=True,
        )), {damas.pk, varones.pk})
        self.assertEqual(obtener_categoria_automatica(
            date(1990, 3, 10), "DAMAS", temporada=2026,
        ).pk, damas.pk)
        self.assertEqual(obtener_categoria_automatica(
            date(1990, 3, 10), "VARONES", temporada=2026,
        ).pk, varones.pk)
        jugadora_nueva = Jugador.objects.get(pk=jugadora.pk)
        self.assertEqual(jugadora_nueva.rut, "23456789-6")
        asignar_categoria_automatica(jugadora_nueva, temporada=2026)
        self.assertEqual(jugadora_nueva.historial_categorias.count(), 2)

    def test_renombre_conserva_estado_y_reglas_inactivas(self):
        CategoriaAntigua = self.apps_antiguas.get_model("usuarios", "Categoria")
        ReglaAntigua = self.apps_antiguas.get_model("usuarios", "ReglaCategoria")
        categoria = CategoriaAntigua.objects.create(
            nombre="T/C Damas", rama="DAMAS", orden=10, activa=False,
        )
        ReglaAntigua.objects.create(
            categoria=categoria, temporada=2025, edad_min=17, edad_max=99, activa=False,
        )
        categoria_original = CategoriaAntigua.objects.filter(pk=categoria.pk).values().get()
        reglas_originales = list(ReglaAntigua.objects.values())

        self.migrar()

        categoria_original["nombre"] = "Todo Competidor Damas"
        self.assertEqual(Categoria.objects.filter(pk=categoria.pk).values().get(), categoria_original)
        self.assertEqual(list(ReglaCategoria.objects.values()), reglas_originales)

    def test_categorias_canonicas_no_se_modifican(self):
        modelo = self.apps_antiguas.get_model("usuarios", "Categoria")
        modelo.objects.create(nombre="Todo Competidor Damas", rama="DAMAS", orden=10)
        modelo.objects.create(nombre="Todo Competidor Varones", rama="VARONES", orden=11)
        originales = list(modelo.objects.order_by("pk").values())

        self.migrar()

        self.assertEqual(list(Categoria.objects.order_by("pk").values()), originales)

    def test_coexistencia_de_categorias_detiene_migracion_antes_de_escribir(self):
        modelo = self.apps_antiguas.get_model("usuarios", "Categoria")
        UsuarioAntiguo = self.apps_antiguas.get_model("usuarios", "Usuario")
        cuenta = UsuarioAntiguo.objects.create(rut="011111111-1")
        for rama in ("Damas", "Varones"):
            modelo.objects.create(nombre=f"T/C {rama}", rama=rama.upper(), orden=10)
            modelo.objects.create(nombre=f"Todo Competidor {rama}", rama=rama.upper(), orden=10)

        for rama in ("Damas", "Varones"):
            with self.subTest(rama=rama):
                categorias_originales = list(modelo.objects.order_by("pk").values())
                with self.assertRaisesMessage(RuntimeError, f"Categorías adultas coexistentes: 'T/C {rama}'"):
                    self.migrar()
                self.assertEqual(list(modelo.objects.order_by("pk").values()), categorias_originales)
                self.assertEqual(UsuarioAntiguo.objects.get(pk=cuenta.pk).rut, "011111111-1")
                # Resolver únicamente el conflicto artificial para restaurar el test.
                modelo.objects.filter(nombre=f"Todo Competidor {rama}").update(
                    nombre=f"Categoría revisada {rama}",
                )

    def test_formatos_validos_se_normalizan_sin_cambiar_identidades(self):
        UsuarioAntiguo = self.apps_antiguas.get_model("usuarios", "Usuario")
        cuenta = UsuarioAntiguo.objects.create(rut="20.347.119-k")
        jugador = self._crear_jugador_antiguo(rut="011111111-1")
        apoderado = self._crear_apoderado_antiguo(
            rut=" 234567896 ", nombres="Ana", apellidos="Apoderada",
        )

        self.migrar()

        self.assertEqual(Usuario.objects.get(pk=cuenta.pk).rut, "20347119-K")
        self.assertEqual(Jugador.objects.get(pk=jugador.pk).rut, "11111111-1")
        self.assertEqual(Apoderado.objects.get(pk=apoderado.pk).rut, "23456789-6")
        self.assertIsNone(Jugador.objects.get(pk=jugador.pk).usuario_id)
        self.assertIsNone(Apoderado.objects.get(pk=apoderado.pk).usuario_id)

    def test_rut_de_perfil_distinto_de_cuenta_detiene_migracion(self):
        UsuarioAntiguo = self.apps_antiguas.get_model("usuarios", "Usuario")
        JugadorAntiguo = self.apps_antiguas.get_model("usuarios", "Jugador")
        ApoderadoAntiguo = self.apps_antiguas.get_model("usuarios", "Apoderado")
        cuenta = UsuarioAntiguo.objects.create(rut="011111111-1")
        jugador = self._crear_jugador_antiguo(rut="22222222-2", usuario=cuenta)
        apoderado = self._crear_apoderado_antiguo(rut="22222222-2", usuario=cuenta)
        for nombre, modelo, perfil in (
            ("Jugador", JugadorAntiguo, jugador),
            ("Apoderado", ApoderadoAntiguo, apoderado),
        ):
            with self.subTest(perfil=nombre):
                with self.assertRaisesMessage(RuntimeError, f"Identidad inconsistente: {nombre} #{perfil.pk}"):
                    self.migrar()
                self.assertEqual(UsuarioAntiguo.objects.get(pk=cuenta.pk).rut, "011111111-1")
                self.assertEqual(modelo.objects.get(pk=perfil.pk).rut, "22222222-2")
                modelo.objects.filter(pk=perfil.pk).update(rut="11111111-1")

    def test_doble_perfil_sin_cuenta_detiene_migracion(self):
        JugadorAntiguo = self.apps_antiguas.get_model("usuarios", "Jugador")
        ApoderadoAntiguo = self.apps_antiguas.get_model("usuarios", "Apoderado")
        jugador = self._crear_jugador_antiguo(rut="011111111-1")
        apoderado = self._crear_apoderado_antiguo(rut="11111111-1")
        with self.assertRaisesMessage(RuntimeError, "Identidad ambigua entre Jugador"):
            self.migrar()
        self.assertEqual(JugadorAntiguo.objects.get(pk=jugador.pk).rut, "011111111-1")
        self.assertEqual(ApoderadoAntiguo.objects.get(pk=apoderado.pk).rut, "11111111-1")
        ApoderadoAntiguo.objects.filter(pk=apoderado.pk).update(rut="22222222-2")

    def test_doble_perfil_menor_detiene_migracion_aunque_comparta_cuenta(self):
        UsuarioAntiguo = self.apps_antiguas.get_model("usuarios", "Usuario")
        JugadorAntiguo = self.apps_antiguas.get_model("usuarios", "Jugador")
        cuenta = UsuarioAntiguo.objects.create(rut="011111111-1")
        jugador = self._crear_jugador_antiguo(
            rut="11111111-1", usuario=cuenta, fecha_nacimiento=timezone.localdate(),
        )
        self._crear_apoderado_antiguo(rut="11111111-1", usuario=cuenta)
        with self.assertRaisesMessage(RuntimeError, "Identidad ambigua entre Jugador"):
            self.migrar()
        self.assertEqual(UsuarioAntiguo.objects.get(pk=cuenta.pk).rut, "011111111-1")
        self.assertEqual(JugadorAntiguo.objects.get(pk=jugador.pk).fecha_nacimiento, jugador.fecha_nacimiento)
        JugadorAntiguo.objects.filter(pk=jugador.pk).update(fecha_nacimiento=date(1990, 3, 10))

    def test_0011_no_sobrescribe_correos_existentes_ni_credenciales(self):
        executor = MigrationExecutor(connection)
        objetivo = [("usuarios", "0010_apoderado_email_jugador_email_and_more")]
        executor.migrate(objetivo)
        apps = executor.loader.project_state(objetivo).apps
        clave = make_password("ClaveExistenteSegura123!")
        cuenta = apps.get_model("usuarios", "Usuario").objects.create(
            rut="11111111-1", email="cuenta@example.com", password=clave,
        )
        jugador = apps.get_model("usuarios", "Jugador").objects.create(
            rut=cuenta.rut, usuario=cuenta, email="perfil@example.com",
            nombres="Alex", apellidos="Jugador", fecha_nacimiento=date(1990, 3, 10),
            rama="VARONES",
        )
        self.migrar()
        self.assertEqual(Jugador.objects.get(pk=jugador.pk).email, "perfil@example.com")
        self.assertEqual(Usuario.objects.get(pk=cuenta.pk).password, clave)

    def test_colision_de_usuario_detiene_migracion_sin_fusionar_personas(self):
        modelo = self.apps_antiguas.get_model("usuarios", "Usuario")
        primero = modelo.objects.create(rut="011111111-1")
        segundo = modelo.objects.create(rut="11111111-1")
        with self.assertRaisesMessage(RuntimeError, "Colisión de RUT en Usuario"):
            self.migrar()
        self.assertEqual(modelo.objects.get(pk=primero.pk).rut, "011111111-1")
        self.assertEqual(modelo.objects.get(pk=segundo.pk).rut, "11111111-1")
        # Reparar solo el dato artificial para poder restaurar el esquema del test.
        modelo.objects.filter(pk=segundo.pk).update(rut="22222222-2")

    def test_colision_de_jugador_no_modifica_ruts_de_cuentas_anteriores(self):
        UsuarioAntiguo = self.apps_antiguas.get_model("usuarios", "Usuario")
        cuenta = UsuarioAntiguo.objects.create(rut="020347119-K")
        modelo = self.apps_antiguas.get_model("usuarios", "Jugador")
        primero = self._crear_jugador_antiguo(rut="011111111-1")
        segundo = self._crear_jugador_antiguo(rut="11111111-1")
        with self.assertRaisesMessage(RuntimeError, "Colisión de RUT en Jugador"):
            self.migrar()
        self.assertEqual(UsuarioAntiguo.objects.get(pk=cuenta.pk).rut, "020347119-K")
        self.assertEqual(modelo.objects.get(pk=primero.pk).rut, "011111111-1")
        self.assertEqual(modelo.objects.get(pk=segundo.pk).rut, "11111111-1")
        modelo.objects.filter(pk=segundo.pk).update(rut="22222222-2")

    def test_colision_de_apoderado_detiene_migracion_sin_borrar_vinculos(self):
        modelo = self.apps_antiguas.get_model("usuarios", "Apoderado")
        primero = self._crear_apoderado_antiguo(rut="011111111-1")
        segundo = self._crear_apoderado_antiguo(rut="11111111-1")
        with self.assertRaisesMessage(RuntimeError, "Colisión de RUT en Apoderado"):
            self.migrar()
        self.assertEqual(modelo.objects.get(pk=primero.pk).rut, "011111111-1")
        self.assertEqual(modelo.objects.get(pk=segundo.pk).rut, "11111111-1")
        modelo.objects.filter(pk=segundo.pk).update(rut="22222222-2")

    def test_rut_historico_invalido_se_reporta_sin_reescribirlo(self):
        modelo = self.apps_antiguas.get_model("usuarios", "Usuario")
        cuenta = modelo.objects.create(rut="11111111-2")
        with self.assertRaisesMessage(RuntimeError, "RUT inválido en Usuario"):
            self.migrar()
        self.assertEqual(modelo.objects.get(pk=cuenta.pk).rut, "11111111-2")
        modelo.objects.filter(pk=cuenta.pk).update(rut="11111111-1")
