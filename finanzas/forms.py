from datetime import timedelta

from django import forms

from usuarios.models import Jugador
from .models import Beca, Cuota, sumar_meses

from django.db.models import Q


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


class BecaForm(forms.ModelForm):
    jugador = forms.ModelChoiceField(
        queryset=Jugador.objects.none(),
        label="Jugador",
    )

    fecha_inicio = forms.DateField(
        label="Fecha de inicio de la beca",
        widget=forms.DateInput(
            attrs={"type": "date"},
        ),
    )

    class Meta:
        model = Beca
        fields = (
            "jugador",
            "fecha_inicio",
            "observaciones",
        )
        labels = {
            "observaciones": "Observaciones administrativas",
        }
        widgets = {
            "observaciones": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": (
                        "Motivo de la beca o antecedentes "
                        "de la evaluación"
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["jugador"].queryset = (
            Jugador.objects.filter(
                estado=Jugador.Estado.ACTIVO,
            ).order_by(
                "apellidos",
                "nombres",
            )
        )

    def clean(self):
        cleaned_data = super().clean()

        jugador = cleaned_data.get("jugador")
        fecha_inicio = cleaned_data.get("fecha_inicio")

        if not jugador or not fecha_inicio:
            return cleaned_data

        fecha_termino = (
            sumar_meses(fecha_inicio, 6)
            - timedelta(days=1)
        )

        becas_superpuestas = Beca.objects.filter(
             jugador=jugador,
             fecha_inicio__lte=fecha_termino,
             fecha_termino__gte=fecha_inicio,
        ).filter(
        Q(estado__in=[
        Beca.Estado.ACTIVA,
        Beca.Estado.RENOVADA,
    ])
    | Q(
        estado=Beca.Estado.FINALIZADA,
        fecha_finalizacion__isnull=True,
    )
    | Q(
        estado=Beca.Estado.FINALIZADA,
        fecha_finalizacion__gte=fecha_inicio,
    )
)


        if self.instance.pk:
            becas_superpuestas = becas_superpuestas.exclude(
                pk=self.instance.pk,
            )

        if becas_superpuestas.exists():
            self.add_error(
                "jugador",
                (
                    "Este jugador ya tiene una beca activa "
                    "que se superpone con el período seleccionado."
                ),
            )

        return cleaned_data