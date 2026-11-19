from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .storage import almacenamiento_privado, ruta_documento


class DocumentoNormativo(models.Model):
    class Tipo(models.TextChoices):
        REGLAMENTO = "REGLAMENTO", "Reglamento"
        PROTOCOLO = "PROTOCOLO", "Protocolo"
        OTRO = "OTRO", "Documento institucional"

    codigo = models.CharField("código", max_length=60, unique=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["codigo"]
        permissions = [
            ("publicar_documentonormativo", "Puede publicar documentos normativos"),
            ("consultar_documentos_institucionales", "Puede consultar documentos institucionales"),
            ("gestionar_miembros", "Puede autorizar y revocar miembros institucionales"),
        ]

    def __str__(self):
        return self.codigo


class VersionDocumentoNormativo(models.Model):
    class Visibilidad(models.TextChoices):
        INTERNO = "INTERNO", "Interno"
        PUBLICO = "PUBLICO", "Público"

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        VIGENTE = "VIGENTE", "Vigente"
        HISTORICA = "HISTORICA", "Histórica"

    documento = models.ForeignKey(DocumentoNormativo, on_delete=models.PROTECT, related_name="versiones")
    numero = models.PositiveIntegerField()
    version = models.CharField("versión", max_length=32)
    titulo = models.CharField("título", max_length=200)
    visibilidad = models.CharField(max_length=7, choices=Visibilidad.choices, default=Visibilidad.INTERNO)
    fecha_documento = models.DateField("fecha del documento")
    vigente_desde = models.DateField("vigente desde")
    archivo = models.FileField(storage=almacenamiento_privado, upload_to=ruta_documento, blank=True)
    archivo_nombre = models.CharField(max_length=200, blank=True)
    archivo_sha256 = models.CharField(max_length=64, blank=True)
    archivo_tamano = models.PositiveIntegerField(default=0)
    motivo_cambio = models.TextField("justificación de la nueva versión", blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.BORRADOR)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    publicado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    publicado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-numero"]
        indexes = [models.Index(fields=["estado", "vigente_desde"], name="inst_normativa_estado_fecha")]
        constraints = [
            models.UniqueConstraint(fields=["documento", "numero"], name="inst_documento_numero_unico"),
            models.UniqueConstraint(fields=["documento", "version"], name="inst_documento_version_unica"),
            models.UniqueConstraint(fields=["documento"], condition=models.Q(estado="VIGENTE"), name="inst_documento_un_vigente"),
            models.CheckConstraint(condition=models.Q(numero__gte=1), name="inst_documento_numero_positivo"),
            models.CheckConstraint(condition=(models.Q(estado="BORRADOR", publicado_en__isnull=True, publicado_por__isnull=True) | models.Q(estado__in=["VIGENTE", "HISTORICA"], publicado_en__isnull=False, publicado_por__isnull=False)), name="inst_documento_publicacion_coherente"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            anterior = type(self).objects.get(pk=self.pk)
            if anterior.estado != self.Estado.BORRADOR:
                permitidos = {"estado", "actualizada_en"}
                if any(getattr(anterior, f.attname) != getattr(self, f.attname)
                       for f in self._meta.concrete_fields if f.name not in permitidos):
                    raise ValidationError("Una versión publicada conserva su contenido original.")
                if self.estado != anterior.estado and not (
                    anterior.estado == self.Estado.VIGENTE and self.estado == self.Estado.HISTORICA
                ):
                    raise ValidationError("Transición de vigencia no permitida.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las versiones se conservan en el historial.")

    def __str__(self):
        return f"{self.documento.codigo} · {self.version}"


class Acta(models.Model):
    codigo = models.CharField("número de acta", max_length=60, unique=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        permissions = [("publicar_acta", "Puede publicar actas")]

    def __str__(self):
        return self.codigo


class VersionActa(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        PUBLICADA = "PUBLICADA", "Publicada"

    acta = models.ForeignKey(Acta, on_delete=models.PROTECT, related_name="versiones")
    numero = models.PositiveIntegerField()
    titulo = models.CharField("título", max_length=200)
    fecha_reunion = models.DateField("fecha de reunión")
    acuerdos = models.TextField()
    archivo = models.FileField(storage=almacenamiento_privado, upload_to=ruta_documento, blank=True)
    archivo_nombre = models.CharField(max_length=200, blank=True)
    archivo_sha256 = models.CharField(max_length=64, blank=True)
    archivo_tamano = models.PositiveIntegerField(default=0)
    motivo_cambio = models.TextField("justificación de la corrección", blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.BORRADOR)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    publicado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    publicado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-numero"]
        indexes = [models.Index(fields=["estado", "fecha_reunion"], name="inst_acta_estado_fecha")]
        constraints = [
            models.UniqueConstraint(fields=["acta", "numero"], name="inst_acta_numero_unico"),
            models.CheckConstraint(condition=models.Q(numero__gte=1), name="inst_acta_numero_positivo"),
            models.CheckConstraint(condition=(models.Q(estado="BORRADOR", publicado_en__isnull=True, publicado_por__isnull=True) | models.Q(estado="PUBLICADA", publicado_en__isnull=False, publicado_por__isnull=False)), name="inst_acta_publicacion_coherente"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            anterior = type(self).objects.get(pk=self.pk)
            if anterior.estado == self.Estado.PUBLICADA and any(
                getattr(anterior, campo.attname) != getattr(self, campo.attname)
                for campo in self._meta.concrete_fields if campo.name != "actualizada_en"
            ):
                raise ValidationError("Una publicación se corrige mediante una nueva versión justificada.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las versiones del acta se conservan en el historial.")

    def __str__(self):
        return f"{self.acta.codigo} · versión {self.numero}"


class Sancion(models.Model):
    class Estado(models.TextChoices):
        REGISTRADA = "REGISTRADA", "Registrada"
        RESUELTA = "RESUELTA", "Resuelta"
        ANULADA = "ANULADA", "Anulada"

    jugador = models.ForeignKey("usuarios.Jugador", on_delete=models.PROTECT, related_name="+")
    fecha = models.DateField()
    motivo = models.TextField()
    resolucion = models.TextField("resolución", blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.REGISTRADA)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    actualizada_en = models.DateTimeField(auto_now=True)
    resuelta_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    resuelta_en = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["-fecha", "-pk"]
        indexes = [models.Index(fields=["estado", "fecha"], name="inst_sancion_estado_fecha")]
        permissions = [("resolver_sancion", "Puede resolver y anular sanciones")]
        constraints = [
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="inst_sancion_revision_positiva"),
            models.CheckConstraint(condition=(models.Q(estado="REGISTRADA", resuelta_en__isnull=True, resuelta_por__isnull=True) | (models.Q(estado__in=["RESUELTA", "ANULADA"], resuelta_en__isnull=False, resuelta_por__isnull=False) & ~models.Q(resolucion=""))), name="inst_sancion_cierre_coherente"),
        ]

    def clean(self):
        super().clean()
        if self.estado in (self.Estado.RESUELTA, self.Estado.ANULADA) and not self.resolucion.strip():
            raise ValidationError({"resolucion": "La resolución es obligatoria al cerrar un expediente."})

    def delete(self, *args, **kwargs):
        raise ValidationError("El expediente se conserva. Registra una anulación justificada.")

    def __str__(self):
        # Puede aparecer en errores de integridad del admin de Jugador.
        return "Registro interno protegido"


class EventoDisciplinario(models.Model):
    class Accion(models.TextChoices):
        REGISTRADA = "REGISTRADA", "Registro de expediente"
        CORREGIDA = "CORREGIDA", "Corrección justificada"
        RESUELTA = "RESUELTA", "Resolución de expediente"
        ANULADA = "ANULADA", "Anulación justificada"
        CONSULTADA = "CONSULTADA", "Consulta del expediente"

    sancion = models.ForeignKey(Sancion, on_delete=models.PROTECT, related_name="eventos")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    accion = models.CharField(max_length=12, choices=Accion.choices)
    fecha = models.DateTimeField(auto_now_add=True)
    justificacion = models.TextField(blank=True)
    antes = models.JSONField(default=dict, blank=True)
    despues = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-fecha", "-pk"]
        default_permissions = ()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La bitácora disciplinaria sólo admite nuevos eventos.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los eventos disciplinarios se conservan.")

    @property
    def cambios(self):
        etiquetas = {"jugador": "Jugador", "fecha": "Fecha", "motivo": "Motivo", "resolucion": "Resolución", "estado": "Estado"}
        return [{"campo": etiqueta, "antes": self.antes.get(campo, "—"), "despues": self.despues.get(campo, "—")}
                for campo, etiqueta in etiquetas.items()
                if self.antes.get(campo) != self.despues.get(campo)]

    def __str__(self):
        return "Evento interno protegido"
