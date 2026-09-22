from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from .models import Usuario, Apoderado, Jugador
from .services import calcular_edad
from .validators import validar_rut, normalizar_rut


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
        
class InscripcionJugadorForm(forms.Form):
    rut = forms.CharField(
        label="RUT del jugador",
        max_length=12,
        help_text="Sin puntos. Ejemplo: 12345678-5",
    )

    nombres = forms.CharField(
        label="Nombres",
        max_length=100,
    )

    apellidos = forms.CharField(
        label="Apellidos",
        max_length=100,
    )

    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento",
        widget=forms.DateInput(
            attrs={"type": "date"},
        ),
    )

    rama = forms.ChoiceField(
        label="Rama",
        choices=Jugador.Rama.choices,
    )

    telefono = forms.CharField(
        label="Telefono del jugador",
        max_length=20,
        required=False,
    )

    nombre_contacto_emergencia = forms.CharField(
        label="Nombre del contacto de emergencia",
        max_length=150,
        required=False,
    )

    telefono_contacto_emergencia = forms.CharField(
        label="Telefono del contacto de emergencia",
        max_length=20,
        required=False,
    )

    procedencia = forms.ChoiceField(
        label="Procedencia deportiva",
        choices=Jugador.Procedencia.choices,
    )

    club_anterior = forms.CharField(
        label="Club anterior",
        max_length=150,
        required=False,
    )

    peso_kg = forms.DecimalField(
        label="Peso (kg)",
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=0,
    )

    talla_cm = forms.DecimalField(
        label="Talla (cm)",
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=0,
    )

    rut_apoderado = forms.CharField(
        label="RUT del apoderado",
        max_length=12,
        required=False,
    )

    nombres_apoderado = forms.CharField(
        label="Nombres del apoderado",
        max_length=100,
        required=False,
    )

    apellidos_apoderado = forms.CharField(
        label="Apellidos del apoderado",
        max_length=100,
        required=False,
    )

    telefono_apoderado = forms.CharField(
        label="Telefono del apoderado",
        max_length=20,
        required=False,
    )

    parentesco = forms.CharField(
        label="Parentesco",
        max_length=50,
        required=False,
        help_text=(
            "Ejemplo: Madre, Padre o Tutor. "
            "El catalogo definitivo aun debe confirmarse."
        ),
    )

    alerta_tipo = forms.CharField(
        label="Tipo de alerta de salud",
        max_length=100,
        required=False,
        help_text=(
            "Solo informacion necesaria para seguridad/emergencias."
        ),
    )

    alerta_descripcion = forms.CharField(
        label="Descripcion de la alerta",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3},
        ),
    )

    observaciones = forms.CharField(
        label="Observaciones",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3},
        ),
    )

    consentimiento = forms.BooleanField(
        label="Confirmo el consentimiento para enviar la solicitud",
        required=True,
    )

    def __init__(
        self,
        *args,
        apoderado_existente=None,
        **kwargs,
    ):
        self.apoderado_existente = apoderado_existente
        super().__init__(*args, **kwargs)

        if apoderado_existente is not None:
            for nombre_campo in (
                "rut_apoderado",
                "nombres_apoderado",
                "apellidos_apoderado",
                "telefono_apoderado",
            ):
                self.fields.pop(nombre_campo, None)

    def clean_rut(self):
        rut = normalizar_rut(
            self.cleaned_data["rut"]
        )
        validar_rut(rut)

        if Jugador.objects.filter(rut=rut).exists():
            raise forms.ValidationError(
                "Ya existe un jugador registrado con este RUT."
            )

        return rut

    def clean_rut_apoderado(self):
        rut = self.cleaned_data.get("rut_apoderado")

        if not rut:
            return ""

        rut = normalizar_rut(rut)
        validar_rut(rut)

        return rut

    def clean(self):
        cleaned = super().clean()

        fecha_nacimiento = cleaned.get(
            "fecha_nacimiento"
        )

        if not fecha_nacimiento:
            return cleaned

        try:
            edad = calcular_edad(
                fecha_nacimiento,
                timezone.localdate(),
            )
        except DjangoValidationError as exc:
            self.add_error(
                "fecha_nacimiento",
                exc,
            )
            return cleaned

        cleaned["edad_calculada"] = edad

        procedencia = cleaned.get("procedencia")

        if (
            procedencia == Jugador.Procedencia.OTRO_CLUB
            and not (
                cleaned.get("club_anterior") or ""
            ).strip()
        ):
            self.add_error(
                "club_anterior",
                "Debe indicar el club anterior.",
            )

        alerta_tipo = (
            cleaned.get("alerta_tipo") or ""
        ).strip()

        alerta_descripcion = (
            cleaned.get("alerta_descripcion") or ""
        ).strip()

        if bool(alerta_tipo) != bool(alerta_descripcion):
            mensaje = (
                "Si registra una alerta de salud debe "
                "indicar tanto el tipo como la descripción."
            )

            if not alerta_tipo:
                self.add_error(
                    "alerta_tipo",
                    mensaje,
                )

            if not alerta_descripcion:
                self.add_error(
                    "alerta_descripcion",
                    mensaje,
                )

        if edad < 18:
            if self.apoderado_existente is None:
                campos_requeridos = (
                    ("rut_apoderado", "RUT del apoderado"),
                    (
                        "nombres_apoderado",
                        "nombres del apoderado",
                    ),
                    (
                        "apellidos_apoderado",
                        "apellidos del apoderado",
                    ),
                    (
                        "telefono_apoderado",
                        "telefono del apoderado",
                    ),
                    ("parentesco", "parentesco"),
                )

                for campo, etiqueta in campos_requeridos:
                    valor = cleaned.get(campo)

                    if not valor or (
                        isinstance(valor, str)
                        and not valor.strip()
                    ):
                        self.add_error(
                            campo,
                            f"Debe indicar {etiqueta}.",
                        )

                rut_apoderado = cleaned.get(
                    "rut_apoderado"
                )

                rut_jugador = cleaned.get("rut")

                if (
                    rut_apoderado
                    and rut_jugador
                    and rut_apoderado == rut_jugador
                ):
                    self.add_error(
                        "rut_apoderado",
                        (
                            "El jugador y el apoderado "
                            "no pueden utilizar el mismo RUT."
                        ),
                    )

                if (
                    rut_apoderado
                    and Apoderado.objects.filter(
                        rut=rut_apoderado
                    ).exists()
                ):
                    self.add_error(
                        "rut_apoderado",
                        (
                            "Ya existe un apoderado con este RUT. "
                            "Por seguridad, debe iniciar sesion "
                            "con esa cuenta para agregar otro jugador."
                        ),
                    )
            else:
                parentesco = (
                    cleaned.get("parentesco") or ""
                ).strip()

                if not parentesco:
                    self.add_error(
                        "parentesco",
                        "Debe indicar el parentesco.",
                    )

        else:
            telefono = (
                cleaned.get("telefono") or ""
            ).strip()

            nombre_emergencia = (
                cleaned.get(
                    "nombre_contacto_emergencia"
                )
                or ""
            ).strip()

            telefono_emergencia = (
                cleaned.get(
                    "telefono_contacto_emergencia"
                )
                or ""
            ).strip()

            if not telefono:
                self.add_error(
                    "telefono",
                    (
                        "El telefono es obligatorio "
                        "para jugadores adultos."
                    ),
                )

            if not nombre_emergencia:
                self.add_error(
                    "nombre_contacto_emergencia",
                    (
                        "Debe indicar un contacto "
                        "de emergencia."
                    ),
                )

            if not telefono_emergencia:
                self.add_error(
                    "telefono_contacto_emergencia",
                    (
                        "Debe indicar el telefono "
                        "del contacto de emergencia."
                    ),
                )

            if self.apoderado_existente is not None:
                parentesco = (
                    cleaned.get("parentesco") or ""
                ).strip()

                if not parentesco:
                    self.add_error(
                        "parentesco",
                        (
                            "Debe indicar el parentesco "
                            "para asociar este jugador."
                        ),
                    )

        return cleaned
    
class RechazoSolicitudForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo del rechazo",
        widget=forms.Textarea(
            attrs={"rows": 4},
        ),
        max_length=2000,
    )

    def clean_motivo(self):
        motivo = self.cleaned_data["motivo"].strip()

        if not motivo:
            raise forms.ValidationError(
                "Debe indicar el motivo del rechazo."
            )

        return motivo