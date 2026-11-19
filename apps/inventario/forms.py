import re
from decimal import Decimal, InvalidOperation

from django import forms

from apps.almacenes.formularios import FormularioBootstrap

from .models import MOTIVOS_AJUSTE_MANUAL, Categoria, UnidadContenido
from .servicios import (
    CONTENIDO_MAXIMO,
    FILTROS_STOCK,
    LARGO_DESCRIPCION,
    MENSAJE_DOS_CATEGORIAS,
    ORDENES_INVENTARIO,
    SIN_CATEGORIA,
)

# Cómo escribe la gente la unidad del envase -> valor de UnidadContenido. Sin tildes ni
# mayúsculas: se comparan en minúscula y sin el punto final («Kg.», «lts»).
UNIDADES_ESCRITAS = {
    **dict.fromkeys(["g", "gr", "grs", "gramo", "gramos"], "g"),
    **dict.fromkeys(["kg", "kgs", "kilo", "kilos", "kilogramo", "kilogramos"], "kg"),
    **dict.fromkeys(["ml", "cc", "c.c", "mililitro", "mililitros"], "ml"),
    **dict.fromkeys(["l", "lt", "lts", "litro", "litros"], "L"),
    **dict.fromkeys(["m", "mt", "mts", "metro", "metros"], "m"),
    **dict.fromkeys(["u", "un", "und", "unid", "unidad", "unidades"], "un"),
}
_PATRON_CONTENIDO = re.compile(r"^(?P<numero>\d+(?:[.,]\d+)?)\s*(?P<unidad>[^\d\s].*)?$")


class CampoContenido(forms.CharField):
    """
    Lo que trae el envase, como lo escribe la gente: «350», «350 ml», «1,5 L», «6
    unidades», «500 cc». Devuelve (cantidad, unidad escrita o None); la unidad escrita
    completa el selector de unidad (ProductoForm.clean). Coma o punto decimal.
    """

    def __init__(self, **kwargs):
        super().__init__(max_length=30, **kwargs)

    def widget_attrs(self, widget):
        # Sin teclado numérico: la unidad también se puede escribir.
        return {"autocomplete": "off"}

    def to_python(self, value):
        texto = " ".join((value or "").split())
        if not texto:
            return None, None
        coincide = _PATRON_CONTENIDO.match(texto)
        if not coincide:
            raise forms.ValidationError(
                "Escribe primero la cantidad y después la unidad. Por ejemplo: 350 ml."
            )
        try:
            cantidad = Decimal(coincide["numero"].replace(",", "."))
        except InvalidOperation:  # pragma: no cover - el patrón ya exige dígitos
            raise forms.ValidationError("Escribe la cantidad con números.") from None
        if cantidad <= 0 or cantidad > CONTENIDO_MAXIMO:
            raise forms.ValidationError(
                "El contenido debe ser mayor que cero y menor que un millón."
            )
        if cantidad != cantidad.quantize(Decimal("0.01")):
            raise forms.ValidationError("El contenido admite hasta dos decimales.")
        unidad = None
        if coincide["unidad"]:
            escrita = coincide["unidad"].lower().rstrip(".")
            unidad = UNIDADES_ESCRITAS.get(escrita)
            if unidad is None:
                raise forms.ValidationError(
                    f"No reconozco la unidad «{coincide['unidad']}». "
                    "Usa g, kg, ml, cc, L, m o unidades."
                )
        return cantidad, unidad

    def validate(self, value):
        # La forma la revisa to_python; el campo es opcional.
        pass


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
    contenido = CampoContenido(
        label="Contenido (opcional)",
        required=False,
        help_text="Lo que trae el envase. Escríbelo junto, como «350 ml», «1,5 L» o "
        "«6 unidades», o pon sólo el número y elige la unidad abajo.",
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
    costo = forms.DecimalField(
        label="Costo por unidad ($) (opcional)",
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=0,
        help_text="Lo que te cobra el proveedor por cada unidad. Sirve para calcular tu "
        "ganancia. El vendedor no lo ve.",
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
        self.fields["costo"].widget.attrs.update({"inputmode": "numeric"})
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
                "costo",
                "stock_minimo",
            ]
        )

    def clean(self):
        # Los mismos chequeos que el servicio, para marcar el campo exacto en pantalla.
        datos = super().clean()
        if datos.get("categoria") and (datos.get("categoria_nueva") or "").strip():
            self.add_error("categoria_nueva", MENSAJE_DOS_CATEGORIAS)
        if "contenido" in datos:
            datos["contenido"], escrita = datos["contenido"]
            elegida = datos.get("unidad_contenido")
            if escrita and elegida and escrita != elegida:
                self.add_error(
                    "unidad_contenido",
                    f"En el contenido escribiste «{UnidadContenido(escrita).label}», pero "
                    f"aquí elegiste «{UnidadContenido(elegida).label}». Deja una sola.",
                )
            elif escrita:
                datos["unidad_contenido"] = escrita
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
