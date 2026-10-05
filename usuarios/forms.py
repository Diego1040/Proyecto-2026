from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Usuario

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Apoderado, Jugador
from .services import calcular_edad, obtener_parentesco_inicial
from .validators import (
    ERROR_IDENTIDAD_INSCRIPCION, normalizar_rut, validar_identidad_perfil,
    validar_relacion_apoderado_jugador, validar_reutilizacion_apoderado, validar_rut,
)


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

    peso_kg = forms.DecimalField(
    label="Peso (kg)",
    max_digits=5,
    decimal_places=2,
    min_value=1,
    max_value=300,
    required=False,
    widget=forms.NumberInput(
        attrs={
            "placeholder": "Ej: 58.5",
            "step": "0.01",
            "min": "1",
            "max": "300",
        }
    ),
)

    talla_cm = forms.DecimalField(
    label="Talla (cm)",
    max_digits=5,
    decimal_places=2,
    min_value=40,
    max_value=250,
    required=False,
    widget=forms.NumberInput(
        attrs={
            "placeholder": "Ej: 165",
            "step": "0.01",
            "min": "40",
            "max": "250",
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

        validar_identidad_perfil(Jugador(rut=rut))
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


class InscripcionJugadorForm(InscripcionForm):
    telefono = forms.CharField(
        label="Telefono del jugador",
        max_length=20,
        required=False,
    )

    email = forms.EmailField(
        label="Correo del jugador",
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
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

    email_apoderado = forms.EmailField(
        label="Correo del apoderado",
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    tiene_alerta_salud = forms.ChoiceField(
        label="¿El jugador tiene alguna alerta de salud relevante?",
        choices=[
            ("NO", "No"),
            ("SI", "Sí"),
        ],
        widget=forms.RadioSelect,
        required=True,
    )

    alerta_tipo = forms.CharField(
        label="Tipo de alerta de salud",
        max_length=100,
        required=False,
        help_text=(
            "Solo informacion necesaria para seguridad/emergencias."
        ),
        widget=forms.TextInput(
            attrs={
                "placeholder": (
                    "Ej.: alergia, asma o restriccion relevante"
                ),
            },
        ),
    )

    alerta_descripcion = forms.CharField(
        label="Descripcion de la alerta",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "Indica solo lo necesario para actuar "
                    "de forma segura ante una emergencia."
                ),
            },
        ),
    )

    observaciones = forms.CharField(
        label="Observaciones",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "Agrega aqui cualquier antecedente relevante "
                    "para la solicitud."
                ),
            },
        ),
    )

    def __init__(
        self,
        *args,
        apoderado_existente=None,
        **kwargs,
    ):
        self.apoderado_existente = apoderado_existente
        super().__init__(*args, **kwargs)
        self.fields["parentesco"].required = False
        self.fields["consentimiento"].label = "Confirmo el consentimiento para enviar la solicitud"

        if apoderado_existente is not None:
            if not self.is_bound:
                self.initial.setdefault("parentesco", obtener_parentesco_inicial(apoderado_existente))
            for nombre_campo in (
                "rut_apoderado",
                "nombres_apoderado",
                "apellidos_apoderado",
                "telefono_apoderado",
                "email_apoderado",
            ):
                self.fields.pop(nombre_campo, None)

    def clean_rut(self):
        rut = normalizar_rut(
            self.cleaned_data["rut"]
        )
        validar_rut(rut)

        if Jugador.objects.filter(rut=rut).exists():
            raise forms.ValidationError(ERROR_IDENTIDAD_INSCRIPCION)

        validar_identidad_perfil(Jugador(rut=rut))

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

        procedencia = cleaned.get("procedencia")

        if procedencia != Jugador.Procedencia.OTRO_CLUB:
            cleaned["club_anterior"] = ""

        tiene_alerta_salud = cleaned.get("tiene_alerta_salud")
        alerta_tipo = (cleaned.get("alerta_tipo") or "").strip()

        alerta_descripcion = (cleaned.get("alerta_descripcion") or "").strip()

        if tiene_alerta_salud == "SI":

            if not alerta_tipo:
                self.add_error(
                    "alerta_tipo",
                    "Debe indicar el tipo de alerta de salud.",
                )

            if not alerta_descripcion:
                self.add_error(
                    "alerta_descripcion",
                    "Debe describir la alerta de salud.",
                )

            cleaned["alerta_tipo"] = alerta_tipo
            cleaned["alerta_descripcion"] = alerta_descripcion

        else:
            cleaned["alerta_tipo"] = ""
            cleaned["alerta_descripcion"] = ""

        fecha_nacimiento = cleaned.get("fecha_nacimiento")

        if not fecha_nacimiento:
            return cleaned

        try:
            edad = calcular_edad(
                fecha_nacimiento,
                timezone.localdate(),
            )
        except ValidationError as exc:
            self.add_error(
                "fecha_nacimiento",
                exc,
            )
            return cleaned

        cleaned["edad_calculada"] = edad

        if edad < 18:
            rut_jugador = cleaned.get("rut")
            rut_apoderado = (
                self.apoderado_existente.rut
                if self.apoderado_existente is not None
                else cleaned.get("rut_apoderado")
            )
            if rut_jugador and rut_apoderado:
                try:
                    validar_relacion_apoderado_jugador(
                        jugador=Jugador(rut=rut_jugador, fecha_nacimiento=fecha_nacimiento),
                        apoderado=Apoderado(rut=rut_apoderado),
                    )
                except ValidationError as exc:
                    self.add_error(None, exc)

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
                    ("email_apoderado", "correo del apoderado"),
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

                rut_apoderado = cleaned.get("rut_apoderado")

                if rut_apoderado:
                    apoderado = Apoderado.objects.filter(rut=rut_apoderado).first()
                    if apoderado is not None:
                        try:
                            validar_reutilizacion_apoderado(apoderado, cleaned)
                        except ValidationError as exc:
                            self.add_error("rut_apoderado", exc)
                    else:
                        apoderado = Apoderado(rut=rut_apoderado)
                    try:
                        validar_identidad_perfil(apoderado)
                    except ValidationError as exc:
                        self.add_error("rut_apoderado", exc)

            else:
                if not self.apoderado_existente.email:
                    self.add_error(
                        None,
                        "El apoderado debe tener un correo registrado antes de inscribir a un menor.",
                    )
                parentesco = (cleaned.get("parentesco") or "").strip()

                if not parentesco:
                    self.add_error(
                        "parentesco",
                        "Debe indicar el parentesco.",
                    )

        else:
            if not cleaned.get("email"):
                self.add_error("email", "El correo del jugador adulto es obligatorio.")
            telefono = (cleaned.get("telefono") or "").strip()

            nombre_emergencia = (cleaned.get("nombre_contacto_emergencia") or "").strip()

            telefono_emergencia = (cleaned.get("telefono_contacto_emergencia") or "").strip()

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
                parentesco = (cleaned.get("parentesco") or "").strip()

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
        help_text="Indica el motivo de la resolución. No incluyas información de salud ni otros datos sensibles.",
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
