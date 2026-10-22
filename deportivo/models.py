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
    #HU-06
    hora_inicio = models.TimeField(null=True, blank=True)
    objetivo = models.TextField(blank=True)
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='entrenamiento_a_cargo',
    )

    class Meta:
        ordering = ['-fecha', '-creado_en']

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

class Evento(models.Model):
    class Tipo(models.TextChoices):
        PARTIDO = "PARTIDO", "Partido"
        VIAJE = "VIAJE", "Viaje"
        CAMPEONATO = "CAMPEONATO", "Campeonato"
        CLUB = "CLUB", "Actividad del club"

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    titulo = models.CharField(max_length=150)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="eventos",
    )
    fecha = models.DateField()
    hora = models.TimeField()
    lugar = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="eventos_creados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "hora"]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.titulo} ({self.fecha:%d-%m-%Y})"

class Nomina(models.Model):
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="nominas",
    )
    # Partido o campeonato del calendario (opcional)
    evento = models.ForeignKey(
        Evento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nominas",
    )
    titulo = models.CharField(max_length=150)
    fecha = models.DateField()
    lugar = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="nominas_creadas",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-creado_en"]

    def __str__(self):
        return f"Nómina {self.titulo} - {self.categoria} ({self.fecha:%d-%m-%Y})"


class NominaJugador(models.Model):
    nomina = models.ForeignKey(
        Nomina,
        on_delete=models.CASCADE,
        related_name="integrantes",
    )
    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.PROTECT,
        related_name="nominas",
    )
    # Foto del momento: la asistencia que tenía cuando se generó la nómina
    asistencia_porcentaje = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["jugador__apellidos", "jugador__nombres"]
        constraints = [
            models.UniqueConstraint(
                fields=["nomina", "jugador"],
                name="jugador_unico_por_nomina",
            )
        ]

    def __str__(self):
        return f"{self.jugador} en {self.nomina}"