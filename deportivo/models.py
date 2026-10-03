from django.conf import settings
from django.db import models

from usuarios.models import Categoria, Jugador

# Create your models here.
class Entrenamiento(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='entrenamientos',)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    duracion = models.IntegerField(help_text="Duración en minutos")
    fecha = models.DateField()
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='entrenamientos_creados')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.nombre} - {self.categoria.nombre} - {self.fecha:%d-%m-%Y}"

class Asistencia(models.Model):
    class Estado(models.TextChoices):
        PRESENTE = 'PRESENTE', 'Presente'
        AUSENTE = 'AUSENTE', 'Ausente'
        JUSTIFICADO = 'JUSTIFICADO', 'Justificado'

    entrenamiento = models.ForeignKey(Entrenamiento, on_delete=models.PROTECT, related_name='asistencias')
    jugador = models.ForeignKey(Jugador, on_delete=models.PROTECT, related_name='asistencias')
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PRESENTE)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='asistencias_registradas')
    registrado_en = models.DateTimeField(auto_now_add=True)
    modificado_en = models.DateTimeField(auto_now=True)
    motivo_modificacion = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['entrenamiento', 'jugador'], name='asistencia_unica_por_asistencia')
        ]

    def __str__(self):
        return f"{self.jugador.nombres} - {self.entrenamiento.nombre} - {self.get_estado_display()}"

class PerfilEntrenador(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil_entrenador')
    categorias = models.ManyToManyField(Categoria, blank=True, related_name='entrenadores')

    class Meta:
        verbose_name = 'Perfil de Entrenador'
        verbose_name_plural = 'Perfiles de Entrenadores'

    def __str__(self):
        return f"Entrenador: {self.usuario.username}"