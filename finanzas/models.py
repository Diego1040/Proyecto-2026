import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from usuarios.models import Jugador


def generar_orden_compra():
    """Genera un identificador único para la transacción Webpay."""
    return uuid.uuid4().hex[:26]


def generar_session_id():
    """Genera un identificador para la sesión de pago."""
    return uuid.uuid4().hex


class Cuota(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        PAGADA = "PAGADA", "Pagada"
        ANULADA = "ANULADA", "Anulada"

    jugador = models.ForeignKey(
        Jugador,
        on_delete=models.PROTECT,
        related_name="cuotas",
    )

    concepto = models.CharField(
        max_length=100,
        default="Cuota mensual",
    )

    # Utilizaremos el primer día del mes como período.
    # Ejemplo: 2026-10-01 representa octubre de 2026.
    periodo = models.DateField(
        help_text="Indica el primer día del mes de la cuota.",
    )

    monto = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("1"))],
    )

    fecha_vencimiento = models.DateField()

    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-periodo", "jugador__apellidos"]
        constraints = [
            models.UniqueConstraint(
                fields=["jugador", "periodo"],
                name="finanzas_una_cuota_por_jugador_mes",
            ),
        ]

    def clean(self):
        super().clean()

        if self.periodo and self.periodo.day != 1:
            raise ValidationError({
                "periodo": (
                    "El período debe comenzar el primer día del mes."
                )
            })

        if (
            self.fecha_vencimiento
            and self.periodo
            and self.fecha_vencimiento < self.periodo
        ):
            raise ValidationError({
                "fecha_vencimiento": (
                    "El vencimiento no puede ser anterior al período."
                )
            })

    def __str__(self):
        return (
            f"{self.jugador.nombres} {self.jugador.apellidos} - "
            f"{self.periodo:%m/%Y} - ${self.monto}"
        )


class Pago(models.Model):
    class Estado(models.TextChoices):
     INICIADO = "INICIADO", "Pago iniciado"
     CONFIRMADO = "CONFIRMADO", "Pago confirmado"
     RECHAZADO = "RECHAZADO", "Pago rechazado"
     ANULADO = "ANULADO", "Pago anulado"
     ERROR = "ERROR", "Error de pago"
     EXPIRADO = "EXPIRADO", "Token expirado"

    class MedioPago(models.TextChoices):
        WEBPAY = "WEBPAY", "Webpay"
        EFECTIVO = "EFECTIVO", "Efectivo"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
        POS = "POS", "Débito / POS"
        OTRO = "OTRO", "Otro autorizado"

    medio_pago = models.CharField(
        max_length=20,
        choices=MedioPago.choices,
        default=MedioPago.WEBPAY,
    )

    referencia = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Número de comprobante o referencia del pago manual.",
    )

###
    cuota = models.ForeignKey(
        Cuota,
        on_delete=models.PROTECT,
        related_name="pagos",
    )



    # Usuario que inició el pago.
    # Puede ser el apoderado autorizado o el propio jugador adulto.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pagos_iniciados",
    )

    orden_compra = models.CharField(
        max_length=26,
        unique=True,
        default=generar_orden_compra,
    )

    session_id = models.CharField(
        max_length=61,
        default=generar_session_id,
    )

    # Token entregado por Webpay durante la creación.
    # Nunca almacenamos números de tarjeta ni códigos de seguridad.
    token_ws = models.CharField(
        max_length=128,
        blank=True,
    )

    # Copia del importe al iniciar el pago.
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        validators=[MinValueValidator(Decimal("1"))],
    )

    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.INICIADO,
    )

    codigo_autorizacion = models.CharField(
        max_length=20,
        blank=True,
    )

    codigo_respuesta = models.IntegerField(
        null=True,
        blank=True,
    )

    fecha_transaccion = models.DateTimeField(
        null=True,
        blank=True,
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["cuota"],
                condition=Q(estado="CONFIRMADO"),
                name="finanzas_un_pago_confirmado_por_cuota",
            ),
        ]

    def __str__(self):
        return (
            f"Pago {self.orden_compra} - "
            f"${self.monto} - {self.get_estado_display()}"
        )