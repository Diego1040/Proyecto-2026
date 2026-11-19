from datetime import date
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfWriter

from usuarios.models import Jugador, SolicitudInscripcion, Usuario


def rut(numero):
    suma = sum(int(digito) * (2 + indice % 6) for indice, digito in enumerate(reversed(str(numero))))
    digito = 11 - suma % 11
    return f"{numero}-{'0' if digito == 11 else 'K' if digito == 10 else digito}"


def pdf(nombre="reglamento.pdf"):
    archivo = BytesIO()
    escritor = PdfWriter()
    escritor.add_blank_page(width=300, height=300)
    escritor.write(archivo)
    return SimpleUploadedFile(nombre, archivo.getvalue(), content_type="application/pdf")


class BaseInstitucionalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("configurar_institucional", stdout=StringIO())
        cls.admin = Usuario.objects.create_user(rut=rut(21000001))
        cls.secretaria = Usuario.objects.create_user(rut=rut(21000002))
        cls.comite = Usuario.objects.create_user(rut=rut(21000003))
        cls.miembro = Usuario.objects.create_user(rut=rut(21000004))
        cls.ajeno = Usuario.objects.create_user(rut=rut(21000005))
        for usuario, grupo in ((cls.admin, "Administración"), (cls.secretaria, "Secretaría"), (cls.comite, "Comité de Disciplina"), (cls.miembro, "Miembros autorizados")):
            usuario.groups.add(Group.objects.get(name=grupo))

    def setUp(self):
        self.temporal = TemporaryDirectory(prefix="ayllu-institucional-test-")
        self.addCleanup(self.temporal.cleanup)
        self.raiz = Path(self.temporal.name)
        opciones = override_settings(INSTITUCIONAL_PRIVATE_ROOT=self.raiz)
        opciones.enable()
        self.addCleanup(opciones.disable)

    def datos_documento(self, **cambios):
        datos = {"titulo": "Reglamento del club", "version": "1.0", "visibilidad": "INTERNO", "fecha_documento": timezone.localdate(), "vigente_desde": timezone.localdate(), "motivo_cambio": ""}
        datos.update(cambios)
        return datos

    def jugador_aprobado(self, usuario=None):
        usuario = usuario or self.ajeno
        jugador = Jugador.objects.create(usuario=usuario, rut=usuario.rut, nombres="Deportista", apellidos="Ayllu", fecha_nacimiento=date(1995, 1, 1), rama="VARONES", estado="ACTIVO")
        SolicitudInscripcion.objects.create(jugador=jugador, estado="APROBADA", procedencia="INDEPENDIENTE", consentimiento=True, usuario_autorizado=usuario, revisado_por=self.admin, fecha_revision=timezone.now())
        return jugador
