
from django import forms

from usuarios.models import Jugador
from .models import Cuota


class CuotaForm(forms.ModelForm):
    jugador = forms.ModelChoiceField(
        queryset=Jugador.objects.none(),
        label="Jugador",
    )

    periodo = forms.DateField(
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            attrs={"type": "month"},
            format="%Y-%m",
        ),
        label="Período de la cuota",
    )

    class Meta:
        model = Cuota
        fields = (
            "jugador",
            "concepto",
            "periodo",
            "monto",
            "fecha_vencimiento",
        )
        labels = {
            "concepto": "Concepto",
            "monto": "Monto en pesos chilenos",
            "fecha_vencimiento": "Fecha de vencimiento",
        }
        widgets = {
            "concepto": forms.TextInput(
                attrs={"placeholder": "Cuota mensual"}
            ),
            "monto": forms.NumberInput(
                attrs={"min": "1", "step": "1"}
            ),
            "fecha_vencimiento": forms.DateInput(
                attrs={"type": "date"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["jugador"].queryset = Jugador.objects.order_by(
            "apellidos",
            "nombres",
        )


class PagoManualForm(forms.Form):
    medio_pago = forms.ChoiceField(
        label="Medio de pago",
        choices=(
            ("EFECTIVO", "Efectivo"),
            ("TRANSFERENCIA", "Transferencia"),
            ("POS", "Débito / POS"),
            ("OTRO", "Otro autorizado"),
        ),
    )

    referencia = forms.CharField(
        label="Referencia del comprobante",
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Número de comprobante (opcional)"
            }
        ),
    )
