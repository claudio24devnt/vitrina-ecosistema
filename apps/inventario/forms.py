from django import forms

from apps.almacenes.formularios import FormularioBootstrap

from .models import MOTIVOS_AJUSTE_MANUAL, Categoria


class ProductoForm(FormularioBootstrap):
    """Datos editables del producto. No incluye stock: el stock sólo cambia con movimientos."""

    codigo_barras = forms.CharField(label="Código de barras", max_length=20)
    nombre = forms.CharField(label="Nombre", max_length=150)
    categoria = forms.ModelChoiceField(
        label="Categoría",
        queryset=Categoria.objects.none(),
        required=False,
        empty_label="Sin categoría",
    )
    precio = forms.DecimalField(
        label="Precio de venta ($)", min_value=0, max_digits=10, decimal_places=0
    )
    stock_minimo = forms.IntegerField(
        label="Stock mínimo",
        min_value=0,
        initial=0,
        help_text="Bajo esta cantidad el producto aparece como «stock bajo».",
    )

    def __init__(self, *args, almacen, **kwargs):
        super().__init__(*args, **kwargs)
        # El listado de categorías sólo muestra las del almacén del usuario.
        self.fields["categoria"].queryset = Categoria.objects.del_almacen(almacen)
        self.fields["codigo_barras"].widget.attrs.update(
            {"autocomplete": "off", "inputmode": "numeric"}
        )


class NuevoProductoForm(ProductoForm):
    stock_inicial = forms.IntegerField(
        label="Stock inicial",
        min_value=0,
        initial=0,
        help_text="Unidades que tienes ahora en el almacén.",
    )


class CategoriaForm(FormularioBootstrap):
    nombre = forms.CharField(label="Nueva categoría", max_length=80)


class AjusteInventarioForm(FormularioBootstrap):
    """Sólo los cuatro motivos manuales: los de la caja no se eligen a mano (§7)."""

    cantidad_contada = forms.IntegerField(
        label="¿Cuántas unidades hay realmente?",
        min_value=0,
        help_text="Cuenta lo que hay en el almacén. El sistema calcula la diferencia.",
    )
    motivo = forms.ChoiceField(
        label="Motivo",
        choices=[("", "Elige un motivo")]
        + [(m.value, m.label) for m in MOTIVOS_AJUSTE_MANUAL],
    )
