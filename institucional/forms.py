from django import forms

from usuarios.models import Jugador, Usuario

from .models import DocumentoNormativo, VersionDocumentoNormativo
from .validators import validar_pdf


class JustificacionVersionMixin:
    def __init__(self, *args, requiere_justificacion=True, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["motivo_cambio"]
        campo.required = requiere_justificacion
        if requiere_justificacion:
            campo.help_text = "Obligatoria para una corrección o una versión posterior."
        elif not self.initial.get("motivo_cambio"):
            campo.widget = forms.HiddenInput()
        else:
            campo.label = "Justificación registrada"
            campo.help_text = "Se conserva la justificación de este borrador."

    def clean_motivo_cambio(self):
        if not self.fields["motivo_cambio"].required and "motivo_cambio" not in self.data:
            return self.initial.get("motivo_cambio", "")
        return self.cleaned_data["motivo_cambio"]


class VersionDocumentoForm(JustificacionVersionMixin, forms.Form):
    titulo = forms.CharField(label="Título", max_length=200)
    version = forms.CharField(label="Versión", max_length=32)
    visibilidad = forms.ChoiceField(
        choices=VersionDocumentoNormativo.Visibilidad.choices,
        initial=VersionDocumentoNormativo.Visibilidad.INTERNO,
        help_text="Interno por defecto. Público permite consulta y descarga sin iniciar sesión, únicamente al publicar esta versión como vigente.",
    )
    fecha_documento = forms.DateField(label="Fecha del documento", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    vigente_desde = forms.DateField(label="Vigente desde", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    archivo = forms.FileField(label="PDF", required=False, widget=forms.FileInput(attrs={"accept": ".pdf"}), help_text="Hasta 5 MiB y 200 páginas. Obligatorio para publicar.")
    motivo_cambio = forms.CharField(label="Justificación de la nueva versión", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_archivo(self):
        archivo = self.cleaned_data.get("archivo")
        if archivo:
            validar_pdf(archivo)
        return archivo


class DocumentoNuevoForm(VersionDocumentoForm):
    codigo = forms.CharField(label="Código", max_length=60)
    tipo = forms.ChoiceField(choices=DocumentoNormativo.Tipo.choices)
    field_order = ["codigo", "tipo", "titulo", "version", "visibilidad", "fecha_documento", "vigente_desde", "archivo", "motivo_cambio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, requiere_justificacion=False, **kwargs)


class CuentaChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, cuenta):
        nombre = cuenta.get_full_name()
        return f"{nombre} — {cuenta.rut}" if nombre else cuenta.rut


class MiembroForm(forms.Form):
    destinatario = CuentaChoiceField(label="Cuenta existente", queryset=Usuario.objects.none(), empty_label="Selecciona una cuenta")
    accion = forms.ChoiceField(label="Acción", choices=[("autorizar", "Autorizar consulta institucional"), ("revocar", "Revocar autorización manual")])
    motivo = forms.CharField(label="Motivo y comprobación de pertenencia", widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destinatario"].queryset = Usuario.objects.order_by("rut")


class VersionActaForm(JustificacionVersionMixin, forms.Form):
    titulo = forms.CharField(label="Título", max_length=200)
    fecha_reunion = forms.DateField(label="Fecha de reunión", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    acuerdos = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}))
    archivo = forms.FileField(label="PDF opcional", required=False, widget=forms.FileInput(attrs={"accept": ".pdf"}), help_text="Hasta 5 MiB y 200 páginas.")
    motivo_cambio = forms.CharField(label="Justificación de la corrección", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_archivo(self):
        archivo = self.cleaned_data.get("archivo")
        if archivo:
            validar_pdf(archivo)
        return archivo


class ActaNuevaForm(VersionActaForm):
    codigo = forms.CharField(label="Número de acta", max_length=60)
    field_order = ["codigo", "titulo", "fecha_reunion", "acuerdos", "archivo", "motivo_cambio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, requiere_justificacion=False, **kwargs)


class SancionNuevaForm(forms.Form):
    jugador = forms.ModelChoiceField(queryset=Jugador.objects.none(), empty_label="Selecciona un jugador")
    fecha = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    motivo = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Incluye jugadores inactivos: un expediente no depende de elegibilidad deportiva.
        self.fields["jugador"].queryset = Jugador.objects.order_by("apellidos", "nombres")


class SancionCorreccionForm(SancionNuevaForm):
    resolucion = forms.CharField(label="Texto de resolución", required=False, widget=forms.Textarea(attrs={"rows": 4}), help_text="Corregir este texto no cambia el estado del expediente. Para cerrarlo, utiliza Resolver expediente.")
    justificacion = forms.CharField(label="Justificación de la corrección", widget=forms.Textarea(attrs={"rows": 3}))
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=1)


class SancionResolucionForm(forms.Form):
    resolucion = forms.CharField(label="Resolución", widget=forms.Textarea(attrs={"rows": 5}))
    revision = forms.IntegerField(widget=forms.HiddenInput, min_value=1)


class SancionAnulacionForm(SancionResolucionForm):
    resolucion = forms.CharField(label="Resolución de anulación", widget=forms.Textarea(attrs={"rows": 5}), help_text="Registra la decisión que deja sin efecto el expediente.")
    justificacion = forms.CharField(label="Justificación de la anulación", widget=forms.Textarea(attrs={"rows": 3}), help_text="Explica el fundamento de la decisión. Ambos campos son obligatorios.")
