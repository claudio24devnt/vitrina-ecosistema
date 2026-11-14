from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from django.core.exceptions import ValidationError

from apps.almacenes.formularios import FormularioBootstrap

from .servicios import (
    ingreso_bloqueado,
    ip_del_cliente,
    limpiar_ingresos_fallidos,
    registrar_ingreso_fallido,
)


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


class IngresoForm(AuthenticationForm):
    """Ingreso con límite de intentos fallidos por correo y por IP (servicios.py)."""

    bloqueado = False

    def clean(self):
        email = self.cleaned_data.get("username", "")
        ip = ip_del_cliente(self.request) if self.request else ""
        if ingreso_bloqueado(email, ip):
            self.bloqueado = True
            raise ValidationError("Demasiados intentos fallidos.", code="bloqueado")
        try:
            datos = super().clean()
        except ValidationError:
            registrar_ingreso_fallido(email, ip)
            raise
        limpiar_ingresos_fallidos(email)
        return datos
