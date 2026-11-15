from decimal import Decimal

from django import forms

from apps.almacenes.formularios import FormularioBootstrap

from .models import MOTIVOS_AJUSTE_MANUAL, Categoria, UnidadContenido
from .servicios import (
    FILTROS_STOCK,
    LARGO_DESCRIPCION,
    MENSAJE_DOS_CATEGORIAS,
    ORDENES_INVENTARIO,
    SIN_CATEGORIA,
)


class CampoDecimalConComa(forms.DecimalField):
    """Acepta «1,5» además de «1.5»: en Chile la coma es el separador decimal."""

    widget = forms.TextInput

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        return super().to_python(value)

    def widget_attrs(self, widget):
        # Sin los atributos de NumberInput (step/min): es un campo de texto con teclado
        # numérico en el celular.
        return {"inputmode": "decimal", "autocomplete": "off"}


class ProductoForm(FormularioBootstrap):
    """Datos editables del producto. No incluye stock: el stock sólo cambia con movimientos."""

    codigo_barras = forms.CharField(label="Código de barras", max_length=20)
    nombre = forms.CharField(label="Nombre", max_length=150)
    descripcion = forms.CharField(
        label="Descripción (opcional)",
        max_length=LARGO_DESCRIPCION,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Lo que ayude a reconocerlo: sabor, variedad, marca.",
    )
    contenido = CampoDecimalConComa(
        label="Contenido (opcional)",
        required=False,
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Lo que trae el envase. Por ejemplo: 350 ml, 1 kg, 6 unidades.",
    )
    unidad_contenido = forms.ChoiceField(
        label="Unidad del contenido",
        required=False,
        choices=[("", "Sin contenido")] + list(UnidadContenido.choices),
    )
    categoria = forms.ModelChoiceField(
        label="Categoría",
        queryset=Categoria.objects.none(),
        required=False,
        empty_label="Sin categoría",
    )
    categoria_nueva = forms.CharField(
        label="… o crea una categoría nueva",
        max_length=80,
        required=False,
        help_text="Déjalo vacío si elegiste una de la lista. Si ya existe, se usa esa.",
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
        self.fields["categoria_nueva"].widget.attrs.update({"autocomplete": "off"})
        # Orden en pantalla: identificación, descripción, categoría, precio y stock.
        self.order_fields(
            [
                "codigo_barras",
                "nombre",
                "descripcion",
                "contenido",
                "unidad_contenido",
                "categoria",
                "categoria_nueva",
                "precio",
                "stock_minimo",
            ]
        )

    def clean(self):
        # Los mismos chequeos que el servicio, para marcar el campo exacto en pantalla.
        datos = super().clean()
        if datos.get("categoria") and (datos.get("categoria_nueva") or "").strip():
            self.add_error("categoria_nueva", MENSAJE_DOS_CATEGORIAS)
        contenido = datos.get("contenido")
        unidad = datos.get("unidad_contenido")
        if "contenido" in datos and contenido is not None and not unidad:
            self.add_error("unidad_contenido", "Elige la unidad (ml, g, kg…).")
        if "contenido" in datos and contenido is None and unidad:
            self.add_error("contenido", "Escribe cuánto trae el envase o quita la unidad.")
        return datos


class FiltroInventarioForm(FormularioBootstrap):
    """
    Búsqueda y filtros del inventario (GET). Un valor que no viene de la lista (una URL
    editada a mano) se ignora y se usa el valor por omisión: nunca es un error.
    """

    q = forms.CharField(label="Buscar", max_length=100, required=False)
    categoria = forms.ChoiceField(label="Categoría", required=False)
    stock = forms.ChoiceField(
        label="Stock",
        required=False,
        choices=[
            ("todos", "Todos"),
            ("bajo", "Stock bajo"),
            ("sin", "Sin stock"),
        ],
    )
    orden = forms.ChoiceField(
        label="Ordenar por",
        required=False,
        choices=[
            ("nombre", "Nombre (A a Z)"),
            ("stock", "Menos stock primero"),
            ("precio", "Menor precio primero"),
        ],
    )

    def __init__(self, *args, almacen, **kwargs):
        super().__init__(*args, **kwargs)
        self._categorias = {
            str(c.pk): c for c in Categoria.objects.del_almacen(almacen).order_by("nombre")
        }
        self.fields["categoria"].choices = [
            ("", "Todas"),
            (SIN_CATEGORIA, "Sin categoría"),
            *[(pk, c.nombre) for pk, c in self._categorias.items()],
        ]
        self.fields["q"].widget.input_type = "search"
        self.fields["q"].widget.attrs.update(
            {
                "placeholder": "Nombre, código de barras o descripción",
                "autocomplete": "off",
            }
        )

    def _marcar_invalidos(self):
        # Un filtro con un valor raro se ignora en silencio; no se marca en rojo.
        pass

    def criterios(self):
        """Argumentos para `filtrar_productos`, con valores por omisión seguros."""
        self.is_valid()
        datos = getattr(self, "cleaned_data", {})
        categoria = datos.get("categoria") or None
        if categoria not in (None, SIN_CATEGORIA):
            categoria = self._categorias.get(categoria)
        stock = datos.get("stock")
        orden = datos.get("orden")
        return {
            "texto": (datos.get("q") or "").strip(),
            "categoria": categoria,
            "stock": stock if stock in FILTROS_STOCK else "todos",
            "orden": orden if orden in ORDENES_INVENTARIO else "nombre",
        }


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
