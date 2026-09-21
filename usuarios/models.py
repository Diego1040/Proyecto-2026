from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .validators import normalizar_rut, validar_rut


class UsuarioManager(BaseUserManager):
    """
    Manager personalizado para Usuario.

    El RUT reemplaza al username como identificador
    de autenticación.
    """

    use_in_migrations = True

    def create_user(self, rut, password=None, **extra_fields):
        if not rut:
            raise ValueError("El usuario debe tener un RUT.")

        rut = normalizar_rut(rut)
        validar_rut(rut)

        usuario = self.model(
            rut=rut,
            **extra_fields,
        )

        if password:
            usuario.set_password(password)
        else:
            usuario.set_unusable_password()

        usuario.save(using=self._db)

        return usuario

    def create_superuser(self, rut, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(
                "El superusuario debe tener is_staff=True."
            )

        if extra_fields.get("is_superuser") is not True:
            raise ValueError(
                "El superusuario debe tener is_superuser=True."
            )

        if not password:
            raise ValueError(
                "El superusuario debe tener una contraseña."
            )

        return self.create_user(
            rut=rut,
            password=password,
            **extra_fields,
        )


class Usuario(AbstractUser):
    """
    Usuario utilizado exclusivamente para autenticación,
    autorización y acceso al sistema.

    Los datos deportivos pertenecen a modelos como
    Jugador y Apoderado.
    """

    username = None

    rut = models.CharField(
        "RUT",
        max_length=12,
        unique=True,
        validators=[validar_rut],
        help_text="RUT sin puntos. Ejemplo: 12345678-5",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    objects = UsuarioManager()

    USERNAME_FIELD = "rut"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["rut"]

    def clean(self):
        super().clean()

        if self.rut:
            self.rut = normalizar_rut(self.rut)
            validar_rut(self.rut)

    def save(self, *args, **kwargs):
        if self.rut:
            self.rut = normalizar_rut(self.rut)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.rut

class Categoria(models.Model):
    class Rama(models.TextChoices):
        MIXTO = "MIXTO", "Mixto"
        DAMAS = "DAMAS", "Damas"
        VARONES = "VARONES", "Varones"

    nombre = models.CharField(
        max_length=50,
        unique=True,
    )

    rama = models.CharField(
        max_length=10,
        choices=Rama.choices,
    )

    activa = models.BooleanField(
        default=True,
    )

    orden = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

class ReglaCategoria(models.Model):
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="reglas",
    )

    edad_min = models.PositiveSmallIntegerField()

    edad_max = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    temporada = models.PositiveSmallIntegerField()

    activa = models.BooleanField(
        default=True,
    )

    class Meta:
        verbose_name = "regla de categoría"
        verbose_name_plural = "reglas de categorías"

        ordering = [
            "temporada",
            "edad_min",
            "categoria_id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["categoria", "temporada"],
                name="unique_categoria_temporada",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(edad_max__isnull=True)
                    | models.Q(edad_max__gte=models.F("edad_min"))
                ),
                name="edad_max_mayor_igual_edad_min",
            ),
        ]

    def __str__(self):
        if self.edad_max is None:
            rango = f"{self.edad_min}+"
        else:
            rango = f"{self.edad_min}-{self.edad_max}"

        return (
            f"{self.categoria.nombre} "
            f"({rango}) - {self.temporada}"
        )

class Jugador(models.Model):
    class Rama(models.TextChoices):
        DAMAS = "DAMAS", "Damas"
        VARONES = "VARONES", "Varones"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    class Procedencia(models.TextChoices):
        INDEPENDIENTE = "INDEPENDIENTE", "Independiente"
        OTRO_CLUB = "OTRO_CLUB", "Otro club"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jugador",
    )

    rut = models.CharField(
        max_length=12,
        unique=True,
        validators=[validar_rut],
    )

    nombres = models.CharField(
        max_length=100,
    )

    apellidos = models.CharField(
        max_length=100,
    )

    fecha_nacimiento = models.DateField()

    rama = models.CharField(
        max_length=10,
        choices=Rama.choices,
    )

    telefono = models.CharField(
        max_length=20,
        blank=True,
    )

    nombre_contacto_emergencia = models.CharField(
        max_length=150,
        blank=True,
    )

    telefono_contacto_emergencia = models.CharField(
        max_length=20,
        blank=True,
    )

    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    categoria_actual = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="jugadores",
    )

    fecha_ingreso = models.DateField(
        null=True,
        blank=True,
    )

    procedencia = models.CharField(
        max_length=20,
        choices=Procedencia.choices,
        default=Procedencia.INDEPENDIENTE,
    )

    club_anterior = models.CharField(
        max_length=150,
        blank=True,
    )

    peso_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    talla_cm = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "jugador"
        verbose_name_plural = "jugadores"
        ordering = ["apellidos", "nombres"]

    def __str__(self):
        return f"{self.nombres} {self.apellidos} ({self.rut})"

    @property
    def edad(self):
        if not self.fecha_nacimiento:
            return None

        hoy = timezone.localdate()

        return (
            hoy.year
            - self.fecha_nacimiento.year
            - (
                (hoy.month, hoy.day)
                < (
                    self.fecha_nacimiento.month,
                    self.fecha_nacimiento.day,
                )
            )
        )

    def clean(self):
        super().clean()

        errores = {}

        if self.rut:
            self.rut = normalizar_rut(self.rut)
        
        if (
            self.usuario
            and self.usuario.rut != self.rut
        ):
            errores["usuario"] = (
                "El RUT de la cuenta debe coincidir "
                "con el RUT del jugador."
            )

        if (
            self.fecha_nacimiento
            and self.fecha_nacimiento > timezone.localdate()
        ):
            errores["fecha_nacimiento"] = (
                "La fecha de nacimiento no puede estar en el futuro."
            )

        if (
            self.procedencia == self.Procedencia.OTRO_CLUB
            and not self.club_anterior.strip()
        ):
            errores["club_anterior"] = (
                "Debe indicar el club anterior."
            )

        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if self.rut:
            self.rut = normalizar_rut(self.rut)
            validar_rut(self.rut)

        super().save(*args, **kwargs)

class Apoderado(models.Model):
    """
    Apoderado utilizado exclusivamente para autenticación,
    autorización y acceso al sistema.
    """
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="apoderado",
    )

    rut = models.CharField(
        max_length=12,
        unique=True,
        validators=[validar_rut],
    )

    nombres = models.CharField(
        max_length=100,
    )

    apellidos = models.CharField(
        max_length=100,
    )

    telefono = models.CharField(
        max_length=20,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "apoderado"
        verbose_name_plural = "apoderados"
        ordering = ["apellidos", "nombres"]

    def __str__(self):
        return f"{self.nombres} {self.apellidos} ({self.rut})"

    def clean(self):
        super().clean()

        if self.rut:
            self.rut = normalizar_rut(self.rut)

        if (
            self.usuario
            and self.usuario.rut != self.rut
        ):
            raise ValidationError({
                "usuario": (
                    "El RUT de la cuenta debe coincidir "
                    "con el RUT del apoderado."
                )
            })

    def save(self, *args, **kwargs):
        if self.rut:
            self.rut = normalizar_rut(self.rut)
            validar_rut(self.rut)

        super().save(*args, **kwargs)

class ApoderadoJugador(models.Model):
    apoderado = models.ForeignKey(
        Apoderado,
        on_delete=models.CASCADE,
        related_name="vinculos_jugadores",
    )

    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.CASCADE,
        related_name="vinculos_apoderados",
    )

    parentesco = models.CharField(
        max_length=50,
    )

    es_principal = models.BooleanField(
        default=False,
    )

    puede_gestionar = models.BooleanField(
        default=True,
    )

    activo = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "relacion apoderado-jugador"
        verbose_name_plural = "relaciones apoderado-jugador"

        constraints = [
            models.UniqueConstraint(
                fields=["apoderado", "jugador"],
                name="unique_apoderado_jugador",
            ),
        ]

    def __str__(self):
        return f"{self.apoderado} → {self.jugador}"

    def clean(self):
        super().clean()

        errores = {}

        if self.es_principal and not self.activo:
            errores["es_principal"] = (
                "Un apoderado principal debe estar activo."
            )

        if (
            self.es_principal
            and self.activo
            and self.jugador_id
        ):
            principales = ApoderadoJugador.objects.filter(
                jugador_id=self.jugador_id,
                es_principal=True,
                activo=True,
            )

            if self.pk:
                principales = principales.exclude(pk=self.pk)

            if principales.exists():
                errores["es_principal"] = (
                    "El jugador ya tiene un apoderado principal activo."
                )

        if errores:
            raise ValidationError(errores)

class SolicitudInscripcion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_REVISION = "EN_REVISION", "En revision"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.PROTECT,
        related_name="solicitudes_inscripcion",
    )

    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitudes_realizadas",
    )

    fecha_solicitud = models.DateTimeField(
        auto_now_add=True,
    )

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    procedencia = models.CharField(
        max_length=20,
        choices=Jugador.Procedencia.choices,
    )

    club_anterior = models.CharField(
        max_length=150,
        blank=True,
    )

    observaciones = models.TextField(
        blank=True,
    )

    consentimiento = models.BooleanField(
        default=False,
    )

    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitudes_revisadas",
    )

    fecha_revision = models.DateTimeField(
        null=True,
        blank=True,
    )

    motivo_rechazo = models.TextField(
        blank=True,
    )

    class Meta:
        verbose_name = "solicitud de inscripcion"
        verbose_name_plural = "solicitudes de inscripcion"
        ordering = ["-fecha_solicitud"]

    def __str__(self):
        return (
            f"Solicitud #{self.pk} - "
            f"{self.jugador} - "
            f"{self.get_estado_display()}"
        )

    def clean(self):
        super().clean()

        errores = {}

        if (
            self.procedencia == Jugador.Procedencia.OTRO_CLUB
            and not self.club_anterior.strip()
        ):
            errores["club_anterior"] = (
                "Debe indicar el club anterior."
            )

        if not self.consentimiento:
            errores["consentimiento"] = (
                "Debe existir consentimiento para enviar la solicitud."
            )

        if self.estado == self.Estado.RECHAZADA:
            if not self.motivo_rechazo.strip():
                errores["motivo_rechazo"] = (
                    "Debe indicar el motivo del rechazo."
                )

            if not self.revisado_por:
                errores["revisado_por"] = (
                    "Debe indicar quien reviso la solicitud."
                )

            if not self.fecha_revision:
                errores["fecha_revision"] = (
                    "Debe registrar la fecha de revision."
                )

        if self.estado == self.Estado.APROBADA:
            if not self.revisado_por:
                errores["revisado_por"] = (
                    "Debe indicar quien aprobo la solicitud."
                )

            if not self.fecha_revision:
                errores["fecha_revision"] = (
                    "Debe registrar la fecha de revision."
                )

        if errores:
            raise ValidationError(errores)

class HistorialCategoria(models.Model):
    class TipoCambio(models.TextChoices):
        AUTOMATICO = "AUTOMATICO", "Automatico"
        EXCEPCION_MANUAL = (
            "EXCEPCION_MANUAL",
            "Excepcion manual",
        )
        CAMBIO_TEMPORADA = (
            "CAMBIO_TEMPORADA",
            "Cambio de temporada",
        )

    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.CASCADE,
        related_name="historial_categorias",
    )

    categoria_anterior = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="historial_como_anterior",
    )

    categoria_nueva = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="historial_como_nueva",
    )

    tipo_cambio = models.CharField(
        max_length=20,
        choices=TipoCambio.choices,
    )

    motivo = models.TextField(
        blank=True,
    )

    cambiado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cambios_categoria_realizados",
    )

    fecha = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "historial de categoria"
        verbose_name_plural = "historiales de categorias"
        ordering = ["-fecha"]

    def __str__(self):
        return (
            f"{self.jugador} → "
            f"{self.categoria_nueva} "
            f"({self.get_tipo_cambio_display()})"
        )

    def clean(self):
        super().clean()

        errores = {}

        if (
            self.tipo_cambio == self.TipoCambio.EXCEPCION_MANUAL
        ):
            if not self.motivo.strip():
                errores["motivo"] = (
                    "Una excepcion manual requiere motivo."
                )

            if not self.cambiado_por:
                errores["cambiado_por"] = (
                    "Debe indicar quien realizo la excepcion."
                )

        if (
            self.categoria_anterior_id
            and self.categoria_anterior_id
            == self.categoria_nueva_id
        ):
            errores["categoria_nueva"] = (
                "La categoria nueva debe ser distinta "
                "de la categoria anterior."
            )

        if errores:
            raise ValidationError(errores)

class AlertaSalud(models.Model):
    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.CASCADE,
        related_name="alertas_salud",
    )

    tipo = models.CharField(
        max_length=100,
    )

    descripcion = models.TextField()

    activa = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "alerta de salud"
        verbose_name_plural = "alertas de salud"
        ordering = ["-activa", "tipo"]

    def __str__(self):
        return f"{self.jugador} - {self.tipo}"

class Auditoria(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acciones_auditoria",
    )

    accion = models.CharField(
        max_length=100,
    )

    entidad = models.CharField(
        max_length=100,
    )

    entidad_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )

    detalle = models.JSONField(
        default=dict,
        blank=True,
    )

    fecha = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "auditoria"
        verbose_name_plural = "auditorias"
        ordering = ["-fecha"]

    def __str__(self):
        return (
            f"{self.accion} - "
            f"{self.entidad} #{self.entidad_id}"
        )