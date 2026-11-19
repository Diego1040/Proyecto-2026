import re

from django.db import migrations
from django.utils import timezone


def _rut_canonico(rut):
    # Regla congelada para que esta migración no dependa de futuros validators.
    limpio = re.sub(r"[.\s-]", "", rut).upper()
    if not re.fullmatch(r"[0-9]+[0-9K]", limpio):
        raise ValueError("Formato de RUT inválido.")

    cuerpo = limpio[:-1].lstrip("0") or "0"
    suma = sum(
        int(digito) * (2 + posicion % 6)
        for posicion, digito in enumerate(reversed(cuerpo))
    )
    resto = 11 - suma % 11
    verificador = "0" if resto == 11 else "K" if resto == 10 else str(resto)
    if limpio[-1] != verificador:
        raise ValueError("Dígito verificador inválido.")
    return f"{cuerpo}-{verificador}"


def normalizar_ruts_y_categorias_adultas(apps, schema_editor):
    alias = schema_editor.connection.alias
    cambios = []
    ruts = {}

    # Comprobar todos los modelos antes de modificar el primer registro.
    for nombre in ("Usuario", "Jugador", "Apoderado"):
        modelo = apps.get_model("usuarios", nombre)
        encontrados = {}
        ruts[nombre] = {}
        for pk, rut in modelo.objects.using(alias).values_list("pk", "rut").iterator():
            try:
                canonico = _rut_canonico(rut)
            except ValueError as exc:
                raise RuntimeError(
                    f"RUT inválido en {nombre} #{pk}. "
                    "Revisa la identidad antes de continuar la migración."
                ) from exc
            if canonico in encontrados:
                raise RuntimeError(
                    f"Colisión de RUT en {nombre}: registros "
                    f"#{encontrados[canonico]} y #{pk}. "
                    "Resuelve la identidad sin fusionar personas automáticamente."
                )
            encontrados[canonico] = pk
            ruts[nombre][pk] = canonico
            if canonico != rut:
                cambios.append((modelo, pk, canonico))

    Jugador = apps.get_model("usuarios", "Jugador")
    Apoderado = apps.get_model("usuarios", "Apoderado")
    jugadores = list(Jugador.objects.using(alias).all())
    apoderados = list(Apoderado.objects.using(alias).all())
    for nombre, perfiles in (("Jugador", jugadores), ("Apoderado", apoderados)):
        for perfil in perfiles:
            if (
                perfil.usuario_id
                and ruts[nombre][perfil.pk] != ruts["Usuario"][perfil.usuario_id]
            ):
                raise RuntimeError(
                    f"Identidad inconsistente: {nombre} #{perfil.pk} y "
                    f"Usuario #{perfil.usuario_id} tienen RUT distintos. "
                    "Requiere revisión manual antes de continuar la migración."
                )

    # El doble perfil solo es inequívoco con la misma cuenta y un jugador adulto.
    apoderados_por_rut = {
        ruts["Apoderado"][perfil.pk]: perfil for perfil in apoderados
    }
    hoy = timezone.localdate()
    for jugador in jugadores:
        apoderado = apoderados_por_rut.get(ruts["Jugador"][jugador.pk])
        if apoderado is None:
            continue
        nacimiento = jugador.fecha_nacimiento
        edad = (
            hoy.year - nacimiento.year
            - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
        ) if nacimiento else None
        if not (
            jugador.usuario_id
            and jugador.usuario_id == apoderado.usuario_id
            and edad is not None and edad >= 18
        ):
            raise RuntimeError(
                f"Identidad ambigua entre Jugador #{jugador.pk} y "
                f"Apoderado #{apoderado.pk}: comparten RUT sin un doble perfil "
                "adulto vinculado a la misma cuenta. Requiere revisión manual."
            )

    Categoria = apps.get_model("usuarios", "Categoria")
    renombres = []
    for rama in ("Damas", "Varones"):
        antigua = Categoria.objects.using(alias).filter(nombre=f"T/C {rama}").first()
        if antigua is None:
            continue

        nombre = f"Todo Competidor {rama}"
        canonica = Categoria.objects.using(alias).filter(nombre=nombre).first()
        if canonica is not None:
            raise RuntimeError(
                f"Categorías adultas coexistentes: '{antigua.nombre}' "
                f"(#{antigua.pk}) y '{nombre}' (#{canonica.pk}). "
                "Requiere revisión manual; no se fusionan categorías ni relaciones."
            )
        renombres.append((antigua.pk, nombre))

    # Todas las comprobaciones terminan antes de la primera escritura.
    for modelo, pk, rut in cambios:
        modelo.objects.using(alias).filter(pk=pk).update(rut=rut)
    for pk, nombre in renombres:
        Categoria.objects.using(alias).filter(pk=pk).update(nombre=nombre)


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0011_datos_activacion_existentes"),
    ]

    operations = [
        # La representación original y los alias no se reconstruyen al revertir.
        migrations.RunPython(
            normalizar_ruts_y_categorias_adultas, migrations.RunPython.noop,
        ),
    ]
