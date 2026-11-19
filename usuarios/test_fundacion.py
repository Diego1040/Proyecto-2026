"""Pruebas de identidad y datos del primer bloque de integración."""
from datetime import date

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .forms import InscripcionForm, UsuarioChangeForm
from .models import Apoderado, ApoderadoJugador, Categoria, Jugador, Usuario
from .services import asignar_categoria_automatica, cambiar_categoria_manual
from .validators import ERROR_IDENTIDAD_INSCRIPCION, normalizar_rut, validar_rut


class IdentidadFundacionTest(TestCase):
    def jugador(self, **cambios):
        datos = {
            "rut": "11111111-1",
            "nombres": "Alex",
            "apellidos": "Jugador",
            "fecha_nacimiento": date(1990, 3, 10),
            "rama": Jugador.Rama.VARONES,
        }
        datos.update(cambios)
        return Jugador(**datos)

    def apoderado(self, **cambios):
        datos = {
            "rut": "11111111-1",
            "nombres": "Alex",
            "apellidos": "Apoderado",
            "telefono": "+56911111111",
        }
        datos.update(cambios)
        return Apoderado(**datos)

    def test_normaliza_ceros_puntos_espacios_y_k_sin_cambiar_verificador(self):
        for entrada, esperado in (
            ("011111111-1", "11111111-1"),
            (" 020.347.119-k ", "20347119-K"),
            ("01.234.567-4", "1234567-4"),
        ):
            with self.subTest(entrada=entrada):
                self.assertEqual(normalizar_rut(entrada), esperado)
                validar_rut(entrada)
        with self.assertRaises(ValidationError):
            validar_rut("011111111-2")

    def test_save_canonicaliza_y_no_permite_duplicados_en_los_tres_modelos(self):
        for fabrica in (
            lambda rut: Usuario(rut=rut),
            lambda rut: self.jugador(rut=rut),
            lambda rut: self.apoderado(rut=rut),
        ):
            with self.subTest(fabrica=fabrica):
                with transaction.atomic():
                    perfil = fabrica("011111111-1")
                    perfil.save()
                    self.assertEqual(perfil.rut, "11111111-1")
                    with self.assertRaises(IntegrityError):
                        with transaction.atomic():
                            fabrica("11111111-1").save()
                    transaction.set_rollback(True)

    def test_full_clean_canonicaliza_los_tres_modelos(self):
        cuenta = Usuario(rut="011111111-1")
        cuenta.set_unusable_password()
        for perfil in (
            cuenta,
            self.jugador(rut="011111111-1"),
            self.apoderado(rut="011111111-1"),
        ):
            perfil.full_clean()
            self.assertEqual(perfil.rut, "11111111-1")

    def test_usuario_save_rechaza_rut_invalido(self):
        with self.assertRaises(ValidationError):
            Usuario(rut="11111111-2").save()
        self.assertFalse(Usuario.objects.exists())

    def test_login_y_busqueda_natural_aceptan_rut_equivalente(self):
        cuenta = Usuario.objects.create_user(
            rut="011111111-1", password="ClaveExistenteSegura123!",
        )
        self.assertEqual(Usuario.objects.get_by_natural_key("11.111.111-1"), cuenta)
        respuesta = self.client.post(reverse("login"), {
            "username": "011111111-1",
            "password": "ClaveExistenteSegura123!",
        })
        self.assertRedirects(respuesta, reverse("panel"))

    async def test_busqueda_natural_asincrona_canonicaliza_rut(self):
        cuenta = await Usuario.objects.acreate(rut="011111111-1")
        self.assertEqual(await Usuario.objects.aget_by_natural_key("11.111.111-1"), cuenta)

    def test_cruce_sin_cuenta_se_bloquea_en_ambas_direcciones(self):
        for primero, segundo in (
            (self.jugador, self.apoderado),
            (self.apoderado, self.jugador),
        ):
            with transaction.atomic():
                primero().save()
                perfil = segundo(rut="011111111-1")
                with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
                    perfil.full_clean()
                with self.assertRaisesMessage(ValidationError, ERROR_IDENTIDAD_INSCRIPCION):
                    perfil.save()
                transaction.set_rollback(True)

    def test_doble_perfil_adulto_explicito_conserva_cuenta_y_contactos(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1", email="cuenta@example.com")
        jugador = self.jugador(usuario=cuenta, email="jugador@example.com")
        jugador.save()
        apoderado = self.apoderado(usuario=cuenta, email="apoderado@example.com")
        apoderado.full_clean()
        apoderado.save()
        jugador.telefono = "+56922222222"
        jugador.save(update_fields=["telefono", "updated_at"])
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.jugador.pk, jugador.pk)
        self.assertEqual(cuenta.apoderado.pk, apoderado.pk)
        self.assertEqual(cuenta.email, "cuenta@example.com")
        self.assertEqual(apoderado.email, "apoderado@example.com")

    def test_menor_no_puede_compartir_doble_perfil(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        self.apoderado(usuario=cuenta).save()
        with self.assertRaises(ValidationError):
            self.jugador(usuario=cuenta, fecha_nacimiento=date(2013, 3, 10)).save()

    def test_perfil_no_puede_vincular_cuenta_de_otro_rut(self):
        cuenta = Usuario.objects.create_user(rut="22222222-2")
        for perfil in (self.jugador(usuario=cuenta), self.apoderado(usuario=cuenta)):
            with self.assertRaises(ValidationError):
                perfil.full_clean()
            with self.assertRaises(ValidationError):
                perfil.save()
        self.assertFalse(Jugador.objects.exists())
        self.assertFalse(Apoderado.objects.exists())

    def test_rut_vinculado_no_cambia_desde_cuenta_perfil_o_formulario(self):
        for fabrica in (self.jugador, self.apoderado):
            with transaction.atomic():
                cuenta = Usuario.objects.create_user(rut="11111111-1")
                perfil = fabrica(usuario=cuenta)
                perfil.save()
                cuenta.rut = "33333333-3"
                with self.assertRaises(ValidationError):
                    cuenta.full_clean()
                with self.assertRaises(ValidationError):
                    cuenta.save(update_fields=["rut"])
                cuenta.refresh_from_db()
                formulario = UsuarioChangeForm({
                    "rut": "33333333-3", "email": "", "is_active": True,
                }, instance=cuenta)
                self.assertFalse(formulario.is_valid())
                perfil.rut = "22222222-2"
                with self.assertRaises(ValidationError):
                    perfil.save(update_fields=["rut"])
                perfil.refresh_from_db()
                self.assertEqual(perfil.rut, "11111111-1")
                transaction.set_rollback(True)

    def test_formato_equivalente_y_contacto_no_cambian_identidad(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        self.apoderado(usuario=cuenta).save()
        cuenta.rut = "011111111-1"
        cuenta.full_clean()
        cuenta.email = "contacto@example.com"
        cuenta.save()
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.rut, "11111111-1")
        self.assertEqual(cuenta.email, "contacto@example.com")

    def test_cuenta_sin_perfil_permite_correccion_de_rut(self):
        cuenta = Usuario.objects.create_user(rut="11111111-1")
        cuenta.rut = "22222222-2"
        cuenta.full_clean()
        cuenta.save()
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.rut, "22222222-2")

    def test_vinculo_menor_consigo_mismo_se_bloquea_incluso_inactivo(self):
        jugador = self.jugador(fecha_nacimiento=date(2013, 3, 10))
        jugador.save()
        apoderado = self.apoderado()
        # Simular una inconsistencia histórica sin eludirla en las vías normales.
        Apoderado.objects.bulk_create([apoderado])
        for activo in (True, False):
            vinculo = ApoderadoJugador(
                jugador=jugador, apoderado=apoderado, parentesco="TUTOR", activo=activo,
            )
            with self.assertRaises(ValidationError):
                vinculo.full_clean()
            with self.assertRaises(ValidationError):
                vinculo.save()
        self.assertFalse(ApoderadoJugador.objects.exists())

    def test_formulario_actual_rechaza_colision_con_apoderado(self):
        self.apoderado().save()
        formulario = InscripcionForm({
            "rut": "011111111-1", "nombres": "Alex", "apellidos": "Jugador",
            "fecha_nacimiento": "2013-03-10", "rama": Jugador.Rama.VARONES,
            "parentesco": "Madre", "procedencia": Jugador.Procedencia.INDEPENDIENTE,
            "consentimiento": "on",
        })
        self.assertFalse(formulario.is_valid())
        self.assertIn(ERROR_IDENTIDAD_INSCRIPCION, str(formulario.errors))


class CategoriasFundacionTest(TestCase):
    def test_recargar_conserva_ids_adultos_y_no_crea_variantes_tc(self):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        originales = list(Categoria.objects.filter(
            nombre__startswith="Todo Competidor",
        ).values_list("pk", "nombre"))
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        self.assertEqual(list(Categoria.objects.filter(
            nombre__startswith="Todo Competidor",
        ).values_list("pk", "nombre")), originales)
        self.assertEqual(len(originales), 2)
        self.assertFalse(Categoria.objects.filter(nombre__startswith="T/C").exists())

    def test_excepcion_adulta_se_conserva_con_nuevos_campos_de_contacto(self):
        call_command("cargar_categorias", temporada=2026, verbosity=0)
        usuario = Usuario.objects.create_user(rut="22222222-2")
        jugador = Jugador.objects.create(
            rut="11111111-1", nombres="Alex", apellidos="Jugador",
            fecha_nacimiento=date(1990, 3, 10), rama=Jugador.Rama.VARONES,
            email="adulto@example.com", nombre_contacto_emergencia="Contacto",
            telefono_contacto_emergencia="+56911111111",
        )
        asignar_categoria_automatica(jugador, temporada=2026)
        cambiar_categoria_manual(
            jugador, Categoria.objects.get(nombre="U17 Varones"), usuario, "Excepción autorizada",
        )
        asignar_categoria_automatica(jugador, temporada=2026)
        jugador.refresh_from_db()
        self.assertEqual(jugador.categoria_actual.nombre, "U17 Varones")
        self.assertEqual(jugador.email, "adulto@example.com")
        self.assertEqual(jugador.historial_categorias.count(), 2)
