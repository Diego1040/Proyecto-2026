from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Usuario

from django import forms
from django.core.exceptions import ValidationError

from .models import Jugador
from .validators import normalizar_rut, validar_rut


class UsuarioCreationForm(UserCreationForm):
    class Meta:
        model = Usuario
        fields = (
            "rut",
            "email",
        )


class UsuarioChangeForm(UserChangeForm):
    class Meta:
        model = Usuario
        fields = (
            "rut",
            "email",
            "is_active",
            "is_staff",
            "is_superuser",
        )




class InscripcionForm(forms.Form):
    nombres = forms.CharField(
        label="Nombres",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Tomás",
            }
        ),
    )

    apellidos = forms.CharField(
        label="Apellidos",
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Vergara Cortés",
            }
        ),
    )

    rut = forms.CharField(
        label="RUT",
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "placeholder": "21.345.678-9",
            }
        ),
    )

    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento",
        widget=forms.DateInput(
            attrs={
                "type": "date",
            }
        ),
    )

    rama = forms.ChoiceField(
        label="Rama",
        choices=Jugador.Rama.choices,
    )

    parentesco = forms.CharField(
        label="Parentesco con el jugador",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Madre, padre, tutor...",
            }
        ),
    )

    procedencia = forms.ChoiceField(
        label="Procedencia",
        choices=Jugador.Procedencia.choices,
    )

    club_anterior = forms.CharField(
        label="Club anterior",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Nombre del club anterior",
            }
        ),
    )

    consentimiento = forms.BooleanField(
        required=True,
        label=(
            "Autorizo el tratamiento de los datos de mi pupilo "
            "con fines estrictamente deportivos y de emergencia."
        ),
    )

    def clean_rut(self):
        rut = normalizar_rut(self.cleaned_data["rut"])
        validar_rut(rut)

        if Jugador.objects.filter(rut=rut).exists():
            raise ValidationError(
                "Ya existe un jugador registrado con este RUT."
            )

        return rut

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data["fecha_nacimiento"]

        from django.utils import timezone

        if fecha > timezone.localdate():
            raise ValidationError(
                "La fecha de nacimiento no puede estar en el futuro."
            )

        return fecha

    def clean(self):
        cleaned_data = super().clean()

        procedencia = cleaned_data.get("procedencia")
        club_anterior = cleaned_data.get("club_anterior", "").strip()

        if (
            procedencia == Jugador.Procedencia.OTRO_CLUB
            and not club_anterior
        ):
            self.add_error(
                "club_anterior",
                "Debes indicar el club anterior."
            )

        return cleaned_data