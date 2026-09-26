import re

from django.core.exceptions import ValidationError


def normalizar_rut(rut: str) -> str:
    """
    Normaliza un RUT chileno al formato XXXXXXXX-X.

    Ejemplos:
        12.345.678-5 -> 12345678-5
        123456785    -> 12345678-5
        12.345.678-k -> 12345678-K
    """
    if not rut:
        return rut

    rut_limpio = re.sub(r"[.\s-]", "", str(rut)).upper()

    if len(rut_limpio) < 2:
        return rut_limpio

    cuerpo = rut_limpio[:-1]
    digito_verificador = rut_limpio[-1]

    return f"{cuerpo}-{digito_verificador}"


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