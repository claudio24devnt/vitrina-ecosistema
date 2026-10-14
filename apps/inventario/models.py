from django.db import models


class Categoria(models.Model):
    id_categoria = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    """
    Sin campo de baja logica: el diccionario de datos define exactamente
    estos campos. La "baja" de un producto es un delete real, pero
    Producto esta protegido (on_delete=PROTECT) desde MovimientoStock y
    DetalleVenta, asi que un producto con historial no se puede eliminar
    fisicamente (la vista debe capturar ProtectedError y avisar al usuario).
    """

    id_producto = models.AutoField(primary_key=True)
    codigo_barras = models.CharField(max_length=32, unique=True)
    nombre = models.CharField(max_length=200)
    id_categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        db_column="id_categoria",
        related_name="productos",
    )
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    stock_actual = models.PositiveIntegerField(default=0)
    stock_minimo = models.PositiveIntegerField(default=0)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.codigo_barras})"

    @property
    def stock_bajo(self):
        return self.stock_actual <= self.stock_minimo


class TipoMovimiento(models.TextChoices):
    ENTRADA = "entrada", "Entrada"
    SALIDA = "salida", "Salida"
    AJUSTE = "ajuste", "Ajuste"


class MovimientoStock(models.Model):
    """Bitacora de auditoria: toda variacion de Producto.stock_actual genera un registro."""

    id_movimiento = models.AutoField(primary_key=True)
    id_producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        db_column="id_producto",
        related_name="movimientos",
    )
    tipo = models.CharField(max_length=10, choices=TipoMovimiento.choices)
    cantidad = models.PositiveIntegerField()
    fecha_hora = models.DateTimeField(auto_now_add=True)
    id_venta = models.ForeignKey(
        "ventas.Venta",
        on_delete=models.PROTECT,
        db_column="id_venta",
        related_name="movimientos_stock",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        ordering = ["-fecha_hora"]

    def __str__(self):
        return f"{self.tipo} x{self.cantidad} - {self.id_producto.nombre}"
