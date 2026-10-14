from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.almacenes.aislamiento import ModeloDeAlmacen


class Categoria(ModeloDeAlmacen):
    id_categoria = models.BigAutoField(primary_key=True, db_column="id_categoria")
    nombre = models.CharField(max_length=80)

    class Meta:
        db_table = "categoria"
        default_manager_name = "sin_aislamiento"
        ordering = ["nombre"]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        constraints = [
            models.UniqueConstraint(fields=["id_almacen", "nombre"], name="uq_categoria")
        ]

    def __str__(self):
        return self.nombre


class Producto(ModeloDeAlmacen):
    """
    Sin baja lógica: el modelo físico no la tiene. Producto está protegido desde
    MovimientoStock y DetalleVenta, así que uno con historial no se puede borrar.
    `stock_actual` sólo cambia a través de la capa de servicios, que deja el
    MovimientoStock correspondiente.
    """

    id_producto = models.BigAutoField(primary_key=True, db_column="id_producto")
    id_categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        db_column="id_categoria",
        related_name="productos",
        null=True,
        blank=True,
        db_index=False,
    )
    codigo_barras = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    precio = models.DecimalField(max_digits=10, decimal_places=0)
    stock_actual = models.IntegerField(default=0, db_default=0)
    stock_minimo = models.IntegerField(default=0, db_default=0)
    fecha_creacion = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "producto"
        default_manager_name = "sin_aislamiento"
        ordering = ["nombre"]
        verbose_name = "producto"
        verbose_name_plural = "productos"
        constraints = [
            models.UniqueConstraint(
                fields=["id_almacen", "codigo_barras"], name="uq_producto"
            ),
            models.CheckConstraint(
                condition=models.Q(stock_actual__gte=0), name="ck_producto_stock_actual"
            ),
        ]
        indexes = [models.Index(fields=["codigo_barras"], name="ix_producto_codigo")]

    def __str__(self):
        return f"{self.nombre} ({self.codigo_barras})"

    @property
    def stock_bajo(self):
        return self.stock_actual <= self.stock_minimo


class TipoMovimiento(models.TextChoices):
    ENTRADA = "entrada", "Entrada"
    SALIDA = "salida", "Salida"
    AJUSTE = "ajuste", "Ajuste"


class MovimientoStock(ModeloDeAlmacen):
    """Bitácora: toda variación de Producto.stock_actual genera un registro."""

    id_movimiento = models.BigAutoField(primary_key=True, db_column="id_movimiento")
    id_producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        db_column="id_producto",
        related_name="movimientos",
        db_index=False,
    )
    id_venta = models.ForeignKey(
        "ventas.Venta",
        on_delete=models.PROTECT,
        db_column="id_venta",
        related_name="movimientos_stock",
        null=True,
        blank=True,
        db_index=False,
    )
    tipo = models.CharField(max_length=10, choices=TipoMovimiento.choices)
    cantidad = models.IntegerField()
    fecha_hora = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "movimiento_stock"
        default_manager_name = "sin_aislamiento"
        ordering = ["-fecha_hora"]
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoMovimiento.values),
                name="ck_movimiento_stock_tipo",
            )
        ]
        indexes = [
            models.Index(fields=["id_producto", "fecha_hora"], name="ix_mov_prod_fecha")
        ]

    def __str__(self):
        return f"{self.tipo} x{self.cantidad} - producto #{self.id_producto_id}"
