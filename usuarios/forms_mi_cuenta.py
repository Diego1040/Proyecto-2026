from django import forms

from .models import Usuario


class MiCuentaForm(forms.ModelForm):
    """Formulario limitado a los datos generales de la cuenta autenticada."""

    class Meta:
        model = Usuario
        fields = ("first_name", "last_name", "email", "telefono")
        labels = {
            "first_name": "Nombres",
            "last_name": "Apellidos",
            "email": "Correo electrónico",
            "telefono": "Teléfono personal",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={
                "autocomplete": "given-name",
                "placeholder": "Tus nombres",
            }),
            "last_name": forms.TextInput(attrs={
                "autocomplete": "family-name",
                "placeholder": "Tus apellidos",
            }),
            "email": forms.EmailInput(attrs={
                "autocomplete": "email",
                "placeholder": "nombre@correo.cl",
            }),
            "telefono": forms.TextInput(attrs={
                "autocomplete": "tel",
                "placeholder": "+56 9 1234 5678",
                "maxlength": "20",
            }),
        }

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()

    def clean_email(self):
        return self.cleaned_data["email"].strip()

    def clean_telefono(self):
        return self.cleaned_data["telefono"].strip()
