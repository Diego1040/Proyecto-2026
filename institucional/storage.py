"""Archivos permanentes privados, independientes de media y de HU19."""

import re
import tempfile
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage


CLAVE_PRIVADA = re.compile(r"(?:normativa|actas)/[0-9a-f]{32}\.pdf\Z")


def raiz_privada():
    ruta = Path(settings.INSTITUCIONAL_PRIVATE_ROOT)
    if not ruta.is_absolute() or ruta.is_symlink():
        raise ImproperlyConfigured("Configura una ruta absoluta privada para Institucional.")
    ruta = ruta.resolve()
    prohibidas = [settings.BASE_DIR, settings.STATIC_ROOT, settings.MEDIA_ROOT,
                  *settings.STATICFILES_DIRS,
                  getattr(settings, "HU19_TEMP_DIR", Path(tempfile.gettempdir()) / "ayllubasket-hu19")]
    for prohibida in prohibidas:
        if prohibida:
            otra = Path(prohibida).resolve()
            if ruta.is_relative_to(otra) or otra.is_relative_to(ruta):
                raise ImproperlyConfigured("Institucional necesita almacenamiento separado de archivos públicos y HU19.")
    return ruta


class AlmacenamientoPrivado(FileSystemStorage):
    def generate_filename(self, filename):
        # Las claves persistidas son POSIX también en Windows.
        nombre = str(filename).replace("\\", "/")
        if not CLAVE_PRIVADA.fullmatch(nombre):
            raise SuspiciousFileOperation("Archivo institucional no disponible.")
        return nombre

    @property
    def location(self):
        return str(raiz_privada())

    def path(self, name):
        if not CLAVE_PRIVADA.fullmatch(str(name)):
            raise SuspiciousFileOperation("Archivo institucional no disponible.")
        raiz = raiz_privada()
        ruta = raiz / name
        if ruta.resolve().parent != raiz / Path(name).parent or ruta.is_symlink():
            raise SuspiciousFileOperation("Archivo institucional no disponible.")
        return str(ruta)

    def get_available_name(self, name, max_length=None):
        # Nunca sobrescribir un archivo de una versión anterior.
        if self.exists(name):
            raise SuspiciousFileOperation("La clave del archivo ya está utilizada.")
        return name

    def url(self, name):
        raise NotImplementedError("Los documentos privados se descargan mediante vistas autorizadas.")


def almacenamiento_privado():
    return AlmacenamientoPrivado(file_permissions_mode=0o600, directory_permissions_mode=0o700)


def ruta_documento(instance, filename):
    carpeta = "actas" if instance._meta.model_name == "versionacta" else "normativa"
    return f"{carpeta}/{uuid4().hex}.pdf"
