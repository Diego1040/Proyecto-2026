import hashlib
from io import BytesIO
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


def validar_pdf(archivo):
    """Valida el contenido, sin confiar en el MIME suministrado por el navegador."""
    limite = settings.INSTITUCIONAL_PDF_MAX_BYTES
    nombre = PurePath(str(archivo.name).replace("\\", "/")).name
    if not nombre.lower().endswith(".pdf") or ":" in nombre:
        raise ValidationError("Selecciona un archivo PDF.")
    try:
        archivo.seek(0)
        contenido = archivo.read(limite + 1)
        if not contenido or len(contenido) > limite:
            raise ValidationError(f"El PDF debe contener datos y no superar {limite / (1024 * 1024):g} MiB.")
        if not contenido.startswith(b"%PDF-"):
            raise ValidationError("El contenido del archivo no es un PDF válido.")
        lector = PdfReader(BytesIO(contenido), strict=True)
        if lector.is_encrypted:
            raise ValidationError("El PDF no debe estar cifrado ni protegido con contraseña.")
        if not 1 <= len(lector.pages) <= settings.INSTITUCIONAL_PDF_MAX_PAGES:
            raise ValidationError(f"El PDF debe tener entre 1 y {settings.INSTITUCIONAL_PDF_MAX_PAGES} páginas.")
        raiz = lector.root_object
        nombres = raiz.get("/Names", {})
        if hasattr(nombres, "get_object"):
            nombres = nombres.get_object()
        if any(campo in raiz for campo in ("/OpenAction", "/AA", "/AF")) or any(
            campo in nombres for campo in ("/JavaScript", "/EmbeddedFiles")
        ):
            raise ValidationError("El PDF no puede contener acciones automáticas ni archivos adjuntos.")
        for pagina in lector.pages:
            if "/AA" in pagina:
                raise ValidationError("El PDF contiene acciones automáticas.")
            for referencia in pagina.get("/Annots", []):
                anotacion = referencia.get_object()
                accion = anotacion.get("/A", {})
                if hasattr(accion, "get_object"):
                    accion = accion.get_object()
                if "/AA" in anotacion or accion.get("/S") in (
                    "/JavaScript", "/Launch", "/SubmitForm", "/ImportData",
                ) or anotacion.get("/Subtype") in ("/FileAttachment", "/RichMedia"):
                    raise ValidationError("El PDF contiene elementos interactivos no permitidos.")
        return {"nombre": nombre[:200], "tamano": len(contenido),
                "sha256": hashlib.sha256(contenido).hexdigest()}
    except (PdfReadError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise ValidationError("No se pudo validar la estructura del PDF.") from error
    finally:
        archivo.seek(0)
