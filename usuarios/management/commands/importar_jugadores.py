"""Validación o importación explícita de la carga histórica de jugadores."""

from django.core.management.base import BaseCommand, CommandError

from usuarios.importacion_jugadores import (
    ErrorArchivoJugadores, ErrorImportacionJugadores, comprobar_destino_reporte,
    escribir_reporte_jugadores, importar_archivo_jugadores, validar_archivo_jugadores,
)


def mostrar(valor):
    texto = "—" if valor is None or str(valor).strip() == "" else str(valor).strip()
    return texto.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")


class Command(BaseCommand):
    help = "Valida o importa jugadores históricos. Requiere --validar o --importar, y --temporada AÑO."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al archivo XLSX con la hoja Hoja1.")
        modos = parser.add_mutually_exclusive_group()
        modos.add_argument("--validar", action="store_true", help="Solo lectura y validación; nunca escribe en BD.")
        modos.add_argument("--importar", action="store_true", help="Importa sólo filas habilitadas en una transacción completa.")
        parser.add_argument("--temporada", type=int, help="Temporada explícita para calcular categoría.")
        parser.add_argument("--reporte", help="Ruta nueva .xlsx para el reporte de revisión.")

    def handle(self, *args, **opciones):
        if opciones["validar"] == opciones["importar"]:
            raise CommandError("Elija exactamente un modo: --validar o --importar. No se escribió ningún dato.")
        if opciones["temporada"] is None:
            raise CommandError("Debe indicar --temporada AÑO para la previsualización.")
        error_importacion = None
        destino = None
        try:
            if opciones["reporte"]:
                destino = comprobar_destino_reporte(opciones["reporte"], opciones["archivo"])
            operacion = importar_archivo_jugadores if opciones["importar"] else validar_archivo_jugadores
            informe = operacion(opciones["archivo"], temporada=opciones["temporada"])
        except ErrorArchivoJugadores as error:
            raise CommandError(str(error)) from error
        except ErrorImportacionJugadores as error:
            error_importacion = error
            informe = error.informe
        titulo = "VALIDACIÓN SIN ESCRITURA" if opciones["validar"] else "IMPORTACIÓN"
        self.stdout.write(f"{titulo} | Hoja1 | temporada {informe.temporada} | referencia {informe.fecha_referencia}")
        self.stdout.write("AVTIVO vacío=INACTIVO; procedencia vacía; CONTACTO de apoderado y FEDERADO quedan sólo en el reporte.")
        for fila in informe.filas:
            self.stdout.write(
                f"Fila {fila.fila} | N° {mostrar(fila.numero)} | {fila.estado} | "
                f"categoría Excel: {mostrar(fila.originales['CAT.'])} | "
                f"categoría calculada: {mostrar(fila.categoria_calculada)}"
            )
            self.stdout.write("  Incidencias: " + " ".join(f"[{i.codigo}] {mostrar(i.mensaje)}" for i in fila.incidencias))
        self.stdout.write("Resumen (filas de datos, sin encabezado):")
        for nombre, cantidad in informe.resumen.items():
            self.stdout.write(f"  {nombre}: {cantidad}")
        self.stdout.write("Existentes = filas con RUT en Jugador, Usuario o Apoderado. Existentes/conflictos pueden coincidir con revisión.")
        if opciones["validar"]:
            self.stdout.write("Escrituras realizadas: 0.")
        elif informe.rollback:
            self.stdout.write("ROLLBACK COMPLETO. Jugadores e historiales creados: 0.")
        else:
            self.stdout.write(f"Importación confirmada. Jugadores creados: {informe.resumen['creados']}.")
        if destino is not None:
            try:
                escribir_reporte_jugadores(informe, archivo=opciones["archivo"], destino=destino)
            except (OSError, ValueError) as error:
                raise CommandError(
                    f"No se pudo guardar el reporte: {error}. "
                    f"Creaciones confirmadas en BD: {informe.resumen['creados']}. "
                    f"Rollback: {informe.rollback}."
                ) from error
            self.stdout.write(f"Reporte XLSX: {destino}")
        if error_importacion is not None:
            raise CommandError(str(error_importacion)) from error_importacion
