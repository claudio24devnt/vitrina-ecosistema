from django import forms

from apps.almacenes.formularios import FormularioBootstrap

from .models import MOTIVO_ANULACION_LARGO_MINIMO


class AnularVentaForm(FormularioBootstrap):
    motivo = forms.CharField(
        label="¿Por qué se anula?",
        min_length=MOTIVO_ANULACION_LARGO_MINIMO,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ej.: el cliente devolvió el producto"}),
    )
