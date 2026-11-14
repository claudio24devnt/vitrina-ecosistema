from django import forms
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm, SetPasswordForm

from apps.almacenes.formularios import FormularioBootstrap


class VendedorForm(FormularioBootstrap):
    nombre = forms.CharField(label="Nombre", max_length=120)
    email = forms.EmailField(label="Correo (con él inicia sesión)", max_length=150)
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput, strip=False)
    password_repetida = forms.CharField(
        label="Repite la contraseña", widget=forms.PasswordInput, strip=False
    )

    def clean(self):
        datos = super().clean()
        if datos.get("password") != datos.get("password_repetida"):
            self.add_error("password_repetida", "Las contraseñas no coinciden.")
        return datos


class ContrasenaNuevaForm(FormularioBootstrap):
    """Contraseña que el administrador (u operador) le asigna a otro usuario."""

    password = forms.CharField(
        label="Contraseña nueva", widget=forms.PasswordInput, strip=False
    )
    password_repetida = forms.CharField(
        label="Repite la contraseña nueva", widget=forms.PasswordInput, strip=False
    )

    def clean(self):
        datos = super().clean()
        if datos.get("password") != datos.get("password_repetida"):
            self.add_error("password_repetida", "Las contraseñas no coinciden.")
        return datos


class CambioContrasenaForm(FormularioBootstrap, PasswordChangeForm):
    """Cambio de la contraseña propia: pide la actual (vista de Django)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Contraseña actual"
        self.fields["new_password1"].label = "Contraseña nueva"
        self.fields["new_password1"].help_text = (
            "Al menos 8 caracteres, que no sea sólo números ni parecida a tu nombre o correo."
        )
        self.fields["new_password2"].label = "Repite la contraseña nueva"


class RecuperarContrasenaForm(FormularioBootstrap, PasswordResetForm):
    """Pide el correo para enviar el enlace de recuperación."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].label = "Tu correo (con el que ingresas)"


class ContrasenaRecuperadaForm(FormularioBootstrap, SetPasswordForm):
    """Contraseña nueva desde el enlace del correo."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Contraseña nueva"
        self.fields["new_password1"].help_text = (
            "Al menos 8 caracteres, que no sea sólo números ni parecida a tu nombre o correo."
        )
        self.fields["new_password2"].label = "Repite la contraseña nueva"
