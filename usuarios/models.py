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