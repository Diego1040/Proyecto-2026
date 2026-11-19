from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from .base import rut


class MigracionVisibilidadTest(TransactionTestCase):
    def test_documentos_existentes_siguen_internos_y_conservan_sus_metadatos(self):
        executor = MigrationExecutor(connection)
        finales = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(finales))
        anterior = [("institucional", "0001_initial")]
        executor.migrate(anterior)
        apps = executor.loader.project_state(anterior).apps
        usuario = apps.get_model("usuarios", "Usuario").objects.create(rut=rut(25000001))
        documento = apps.get_model("institucional", "DocumentoNormativo").objects.create(codigo="LEGADO", tipo="REGLAMENTO", creado_por=usuario)
        version = apps.get_model("institucional", "VersionDocumentoNormativo").objects.create(
            documento=documento, numero=1, version="1.0", titulo="Reglamento existente",
            fecha_documento=timezone.localdate(), vigente_desde=timezone.localdate(),
            estado="VIGENTE", creada_por=usuario, publicado_por=usuario, publicado_en=timezone.now(),
        )
        destino = [("institucional", "0002_visibilidad_normativa")]
        executor = MigrationExecutor(connection)
        executor.migrate(destino)
        modelo = executor.loader.project_state(destino).apps.get_model("institucional", "VersionDocumentoNormativo")
        migrada = modelo.objects.get(pk=version.pk)
        self.assertEqual(migrada.visibilidad, "INTERNO")
        self.assertEqual(migrada.estado, "VIGENTE")
        self.assertEqual(migrada.titulo, version.titulo)
        self.assertEqual(migrada.documento_id, documento.pk)
        self.assertEqual(migrada.publicado_por_id, usuario.pk)
