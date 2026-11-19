"""Temporales privados de HU19; no contiene reglas de jugadores ni escribe en BD."""

import hashlib
import json
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .importacion_jugadores import escribir_reporte_jugadores


VIGENCIA_SEGUNDOS = 30 * 60


def _raiz():
    ruta = Path(getattr(
        settings, "HU19_TEMP_DIR", Path(tempfile.gettempdir()) / "ayllubasket-hu19",
    ))
    if ruta.is_symlink():
        raise ImproperlyConfigured("HU19 necesita un directorio temporal privado.")
    ruta = ruta.resolve()
    prohibidas = [settings.BASE_DIR, settings.STATIC_ROOT, settings.MEDIA_ROOT]
    prohibidas.extend(settings.STATICFILES_DIRS)
    for prohibida in prohibidas:
        if prohibida and ruta.is_relative_to(Path(prohibida).resolve()):
            raise ImproperlyConfigured("Los temporales HU19 deben quedar fuera del proyecto y de archivos públicos.")
    ruta.mkdir(mode=0o700, parents=True, exist_ok=True)
    return ruta


def directorio(identificador):
    raiz = _raiz()
    ruta = raiz / UUID(str(identificador)).hex
    if ruta.is_symlink() or ruta.resolve().parent != raiz:
        raise ValueError("Identificador temporal inválido.")
    return ruta


def eliminar(identificador):
    # La ruta resuelta y su padre se comprueban antes de cualquier borrado recursivo.
    ruta = directorio(identificador)
    if ruta.exists():
        shutil.rmtree(ruta)


def limpiar_vencidos():
    limite = timezone.now().timestamp() - VIGENCIA_SEGUNDOS
    for ruta in _raiz().iterdir():
        try:
            if not ruta.is_symlink() and ruta.is_dir() and ruta.stat().st_mtime < limite:
                eliminar(ruta.name)
        except (ValueError, OSError):
            # Otro request puede estar terminando o eliminando el mismo temporal.
            continue


def guardar(archivo):
    identificador = str(uuid4())
    ruta = directorio(identificador)
    ruta.mkdir(mode=0o700)
    try:
        with (ruta / "entrada.xlsx").open("xb") as salida:
            for bloque in archivo.chunks():
                salida.write(bloque)
    except Exception:
        eliminar(identificador)
        raise
    return identificador


def huella_archivo(archivo):
    archivo.seek(0)
    huella = hashlib.file_digest(archivo, "sha256").hexdigest()
    archivo.seek(0)
    return huella


def huella_validacion(informe):
    contenido = json.dumps(asdict(informe), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def guardar_reporte(identificador, informe, nombre):
    reporte_id = uuid4().hex
    carpeta = directorio(identificador)
    escribir_reporte_jugadores(
        informe, archivo=nombre, destino=carpeta / f"reporte-{reporte_id}.xlsx",
    )
    return reporte_id


def ruta_reporte(identificador, reporte_id):
    return directorio(identificador) / f"reporte-{UUID(str(reporte_id)).hex}.xlsx"


@contextmanager
def confirmar_exclusivamente(identificador):
    """Evita dos confirmaciones simultáneas del mismo temporal, sin estado persistente."""
    bloqueo = directorio(identificador) / "confirmando"
    with bloqueo.open("x"):
        pass
    try:
        yield
    finally:
        bloqueo.unlink(missing_ok=True)
