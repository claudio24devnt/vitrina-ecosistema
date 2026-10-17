from django import forms


class FormularioBootstrap(forms.Form):
    """Agrega las clases de Bootstrap 5 a cada campo y marca los que tienen error."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.Select):
                clase = "form-select"
            elif isinstance(widget, forms.CheckboxInput):
                clase = "form-check-input"
            else:
                clase = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {clase}".strip()

    def full_clean(self):
        super().full_clean()
        for nombre in self.errors:
            if nombre in self.fields:
                widget = self.fields[nombre].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()


class AltaAlmacenForm(FormularioBootstrap):
    """Alta de un almacén cliente y su primer administrador (pantalla del operador)."""

    razon_social = forms.CharField(label="Razón social", max_length=120)
    rut = forms.CharField(
        label="RUT del almacén", max_length=12, help_text="Ej.: 76.123.456-7"
    )
    direccion = forms.CharField(label="Dirección", max_length=200, required=False)
    plan = forms.CharField(label="Plan", max_length=20, initial="basico")
    nombre_admin = forms.CharField(label="Nombre del administrador", max_length=120)
    email_admin = forms.EmailField(
        label="Correo del administrador (con él inicia sesión)", max_length=150
    )
    password = forms.CharField(
        label="Contraseña inicial", widget=forms.PasswordInput, strip=False
    )
    password_repetida = forms.CharField(
        label="Repite la contraseña", widget=forms.PasswordInput, strip=False
    )

    def clean(self):
        datos = super().clean()
        if datos.get("password") != datos.get("password_repetida"):
            self.add_error("password_repetida", "Las contraseñas no coinciden.")
        return datos
