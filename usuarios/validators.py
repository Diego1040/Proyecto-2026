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
    """Un cruce de perfiles exige una cuenta explícita; los datos no lo prueban."""
    # Importación diferida: los modelos también utilizan estos validadores.
    from .models import Apoderado, Jugador

    if not perfil.rut:
        return
    rut = normalizar_rut(perfil.rut)
    otro_modelo = Apoderado if isinstance(perfil, Jugador) else Jugador
    otro = otro_modelo.objects.filter(rut=rut).first()
    if otro is None:
        return

    jugador = perfil if isinstance(perfil, Jugador) else otro
    if not (
        perfil.usuario_id
        and perfil.usuario_id == otro.usuario_id
        and normalizar_rut(perfil.usuario.rut) == rut
        and jugador.edad is not None
        and jugador.edad >= 18
    ):
        raise ValidationError(ERROR_IDENTIDAD_INSCRIPCION)


def validar_relacion_apoderado_jugador(*, jugador, apoderado):
    """Un menor nunca puede ser su propio apoderado, tampoco en vínculos inactivos."""
    if jugador.edad is not None and jugador.edad < 18 and (
        normalizar_rut(jugador.rut) == normalizar_rut(apoderado.rut)
        or (jugador.usuario_id and jugador.usuario_id == apoderado.usuario_id)
    ):
        raise ValidationError(ERROR_IDENTIDAD_INSCRIPCION)
