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
