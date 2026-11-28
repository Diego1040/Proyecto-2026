import re

from django.core.exceptions import ValidationError


ERROR_IDENTIDAD_INSCRIPCION = (
    "No es posible completar esta inscripción automáticamente. "
    "Solicita revisión administrativa."
)


def normalizar_rut(rut: str) -> str:
    """
    Normaliza un RUT chileno al formato XXXXXXXX-X.

    Ejemplos:
        12.345.678-5 -> 12345678-5
        123456785    -> 12345678-5
        12.345.678-k -> 12345678-K
        011111111-1 -> 11111111-1
    """
    if not rut:
        return rut

    rut_limpio = re.sub(r"[.\s-]", "", str(rut)).upper()

    if len(rut_limpio) < 2:
        return rut_limpio

    cuerpo = rut_limpio[:-1]
    digito_verificador = rut_limpio[-1]

    if cuerpo.isdecimal():
        cuerpo = cuerpo.lstrip("0") or "0"

    return f"{cuerpo}-{digito_verificador}"


ERROR_TELEFONO = (
    "Ingresa un celular chileno válido: +56 9 seguido de 8 dígitos, por ejemplo +56 9 1234 5678."
)

# Para el navegador (frontend): mismo criterio que validar_telefono
PATRON_TELEFONO_HTML = r"\s*(\+?56)?[\s\-.]*9([\s\-.]*\d){8}\s*"
ATRIBUTOS_TELEFONO = {
    "autocomplete": "tel",
    "inputmode": "tel",
    "placeholder": "+56 9 1234 5678",
    "pattern": PATRON_TELEFONO_HTML,
    "title": "Celular chileno: +56 9 1234 5678",
    "maxlength": "20",
}


def validar_telefono(valor: str) -> str:
    """
    Valida un celular chileno y lo devuelve en formato estándar +56 9 XXXX XXXX.

    - Se puede escribir con o sin +56 (912345678, +56912345678, +56 9 1234-5678).
    - Debe ser un celular: 9 dígitos que comienzan con 9.
    - Un valor vacío se acepta; la obligatoriedad la decide cada formulario.
    """
    valor = (valor or "").strip()
    if not valor:
        return valor
    digitos = re.sub(r"[\s\-().]", "", valor)
    coincidencia = re.fullmatch(r"(?:\+?56)?(9\d{8})", digitos)
    if not coincidencia:
        raise ValidationError(ERROR_TELEFONO)
    numero = coincidencia.group(1)
    return f"+56 {numero[0]} {numero[1:5]} {numero[5:]}"
    digitos = re.sub(r"[\s\-().]", "", valor)
    if not re.fullmatch(r"(\+?56)?\d{9}", digitos):
        raise ValidationError(ERROR_TELEFONO)
    return valor


def validar_rut(rut: str) -> None:
    """
    Valida formato y dígito verificador de un RUT chileno.
    """
    rut_normalizado = normalizar_rut(rut)

    patron = r"^(\d+)-([\dK])$"
    coincidencia = re.match(patron, rut_normalizado)

    if not coincidencia:
        raise ValidationError("Ingrese un RUT válido.")

    cuerpo, digito_verificador = coincidencia.groups()

    suma = 0
    multiplicador = 2

    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador

        multiplicador += 1

        if multiplicador > 7:
            multiplicador = 2

    resto = 11 - (suma % 11)

    if resto == 11:
        digito_calculado = "0"
    elif resto == 10:
        digito_calculado = "K"
    else:
        digito_calculado = str(resto)

    if digito_verificador != digito_calculado:
        raise ValidationError("El dígito verificador del RUT no es válido.")


def validar_identidad_perfil(perfil):
    """El doble perfil adulto requiere una cuenta explícita del mismo RUT."""
    # Importación diferida: los modelos también utilizan estos validadores.
    from .models import Apoderado, Jugador

    if not perfil.rut:
        return

    rut = normalizar_rut(perfil.rut)
    if perfil.usuario_id and normalizar_rut(perfil.usuario.rut) != rut:
        raise ValidationError({
            "usuario": "El RUT de la cuenta debe coincidir con el del perfil.",
        })

    otro_modelo = Apoderado if isinstance(perfil, Jugador) else Jugador
    otro = otro_modelo.objects.using(perfil._state.db).filter(rut=rut).first()
    if otro is None:
        return

    jugador = perfil if isinstance(perfil, Jugador) else otro
    if not (
        perfil.usuario_id
        and perfil.usuario_id == otro.usuario_id
        and jugador.edad is not None
        and jugador.edad >= 18
    ):
        raise ValidationError(ERROR_IDENTIDAD_INSCRIPCION)


def validar_relacion_apoderado_jugador(*, jugador, apoderado):
    """Un menor no puede representarse a sí mismo, ni en vínculos inactivos."""
    if jugador.edad is not None and jugador.edad < 18 and (
        normalizar_rut(jugador.rut) == normalizar_rut(apoderado.rut)
        or (jugador.usuario_id and jugador.usuario_id == apoderado.usuario_id)
    ):
        raise ValidationError(ERROR_IDENTIDAD_INSCRIPCION)


def validar_reutilizacion_apoderado(apoderado, datos):
    """Un perfil público sin cuenta se reutiliza sin modificar su identidad."""
    def comparable(campo, valor):
        valor = (valor or "").strip().casefold()
        if campo == "telefono":
            # +56912345678 y +56 9 1234 5678 son el mismo número
            return re.sub(r"\D", "", valor)[-9:]
        return valor

    if apoderado.usuario_id or any(
        comparable(campo, getattr(apoderado, campo))
        != comparable(campo, datos.get(f"{campo}_apoderado"))
        for campo in ("nombres", "apellidos", "telefono", "email")
    ):
        raise ValidationError(ERROR_IDENTIDAD_INSCRIPCION)


# Parentesco (observación del docente RF-001): lista cerrada, no texto libre.
# Se guarda la etiqueta legible, así no hace falta migrar la base de datos.
PARENTESCOS = (
    "Madre",
    "Padre",
    "Abuelo/a",
    "Tío/a",
    "Hermano/a mayor de edad",
    "Tutor/a legal",
    "Otro familiar responsable",
)
_ALIAS_PARENTESCO = {
    "tutor": "Tutor/a legal",
    "tutora": "Tutor/a legal",
    "abuelo": "Abuelo/a",
    "abuela": "Abuelo/a",
    "tio": "Tío/a",
    "tía": "Tío/a",
    "tia": "Tío/a",
    "tío": "Tío/a",
}
OPCIONES_PARENTESCO = [("", "Selecciona el parentesco")] + [(p, p) for p in PARENTESCOS]
ERROR_PARENTESCO = "Selecciona un parentesco de la lista."


def normalizar_parentesco(valor):
    """Devuelve la opción oficial de la lista, o "" si el valor no corresponde."""
    texto = (valor or "").strip().casefold()
    if not texto:
        return ""
    for opcion in PARENTESCOS:
        if opcion.casefold() == texto:
            return opcion
    return _ALIAS_PARENTESCO.get(texto, "")


def validar_parentesco(valor):
    """Vacío se acepta (la obligatoriedad la decide el formulario); otro valor debe ser de la lista."""
    if not (valor or "").strip():
        return ""
    parentesco = normalizar_parentesco(valor)
    if not parentesco:
        raise ValidationError(ERROR_PARENTESCO)
    return parentesco
