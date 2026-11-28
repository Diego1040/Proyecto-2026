from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .validators import ContrasenaRobustaValidator


class ContrasenaRobustaTest(SimpleTestCase):
    def test_acepta_contrasena_robusta(self):
        for clave in ("Ayllu.Demo2026", "Basket-Arica#15", "ÑandúRápido_99"):
            with self.subTest(clave=clave):
                validate_password(clave)

    def test_rechaza_y_dice_que_falta(self):
        casos = {
            "ayllu.demo2026": "mayúscula",
            "AYLLU.DEMO2026": "minúscula",
            "Ayllu.Demo": "número",
            "AylluDemo2026": "símbolo",
        }
        for clave, falta in casos.items():
            with self.subTest(clave=clave):
                with self.assertRaises(ValidationError) as error:
                    ContrasenaRobustaValidator().validate(clave)
                self.assertIn(falta, error.exception.messages[0])

    def test_largo_minimo_de_8(self):
        with self.assertRaises(ValidationError):
            validate_password("Ab1.cd")


class CambioContrasenaPantallaTest(TestCase):
    """El cambio de contraseña usa la pantalla del club, no la de Django."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(rut="12345678-5", password="Ayllu.Demo2026")
        self.client.force_login(self.usuario)

    def test_pantalla_del_club_con_las_reglas(self):
        respuesta = self.client.get(reverse("password_change"))
        self.assertNotContains(respuesta, "Administración de Django")
        self.assertContains(respuesta, "mayúscula, minúscula, número y símbolo")

    def test_rechaza_contrasena_debil_y_no_la_cambia(self):
        self.client.post(reverse("password_change"), {
            "old_password": "Ayllu.Demo2026", "new_password1": "clave1234", "new_password2": "clave1234",
        })
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("Ayllu.Demo2026"))

    def test_contrasena_robusta_se_cambia_y_muestra_pantalla_del_club(self):
        respuesta = self.client.post(reverse("password_change"), {
            "old_password": "Ayllu.Demo2026", "new_password1": "Basket-Arica#15", "new_password2": "Basket-Arica#15",
        }, follow=True)
        self.assertNotContains(respuesta, "Administración de Django")
        self.assertContains(respuesta, "Contraseña actualizada")
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("Basket-Arica#15"))
