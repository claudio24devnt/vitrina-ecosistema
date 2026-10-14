from django import forms

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
