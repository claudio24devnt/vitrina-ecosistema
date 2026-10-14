from django import forms

from .models import Categoria, Producto


class ProductoForm(forms.ModelForm):
    """Edición de un producto existente. El stock nunca se edita acá directamente:
    toda variación de stock pasa por un MovimientoStock (ver services.py)."""

    class Meta:
        model = Producto
        fields = ["codigo_barras", "nombre", "id_categoria", "precio", "stock_minimo"]
        labels = {
            "codigo_barras": "Código de barras",
            "nombre": "Nombre",
            "id_categoria": "Categoría",
            "precio": "Precio",
            "stock_minimo": "Stock mínimo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["id_categoria"].empty_label = "Seleccioná una categoría"


class NuevoProductoForm(ProductoForm):
    stock_inicial = forms.IntegerField(min_value=0, initial=0, label="Stock inicial")

    field_order = [
        "codigo_barras",
        "nombre",
        "id_categoria",
        "precio",
        "stock_minimo",
        "stock_inicial",
    ]


class SumarStockForm(forms.Form):
    cantidad = forms.IntegerField(min_value=1, label="Cantidad a agregar")


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre"]
