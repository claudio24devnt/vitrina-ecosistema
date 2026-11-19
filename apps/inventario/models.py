from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
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


class UnidadContenido(models.TextChoices):
    """
    Unidad del contenido del envase (2026-11-15). Lista cerrada
    (ck_producto_unidad_contenido): cada unidad nueva es una migración. Sin «cc»: es
    lo mismo que ml y dos nombres para una unidad complican agrupar en la v2.
    """

    GRAMOS = "g", "g"
    KILOS = "kg", "kg"
    MILILITROS = "ml", "ml (cc)"
    LITROS = "L", "L"
    METROS = "m", "m"
    UNIDADES = "un", "unidades"


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
    # Quién dio de alta el producto (1.4.3). NULL en los creados desde el admin de
    # Django o antes de este cambio: no se inventa un autor (§2.3).
    id_usuario_creacion = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario_creacion",
        related_name="productos_creados",
        null=True,
        blank=True,
        db_index=False,
    )
    # 2026-11-15: datos descriptivos opcionales. El contenido («350 ml», «1 kg») no es
    # venta por peso (v2): no toca stock, detalle de venta ni movimientos.
    descripcion = models.CharField(
        max_length=300, null=True, blank=True, db_column="descripcion"
    )
    contenido = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, db_column="contenido"
    )
    unidad_contenido = models.CharField(
        max_length=10,
        choices=UnidadContenido.choices,
        null=True,
        blank=True,
        db_column="unidad_contenido",
    )
    # 2026-11-19: costo por unidad que paga el almacén (último conocido). Opcional: NULL
    # es «no se sabe», nunca cero. Lo ve sólo el administrador. Cada venta copia el
    # vigente en detalle_venta.costo_unitario, así la ganancia de meses pasados no
    # cambia cuando el proveedor sube el precio.
    costo = models.DecimalField(
        max_digits=10, decimal_places=0, null=True, blank=True, db_column="costo"
    )

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
            # Contenido y unidad van juntos: un «350» sin unidad no dice nada. El
            # `contenido IS NOT NULL` explícito no sobra: `NULL > 0` es NULL y un CHECK
            # con NULL se cumple, así que sin él pasaría una unidad sin contenido.
            models.CheckConstraint(
                condition=Q(contenido__isnull=True, unidad_contenido__isnull=True)
                | Q(contenido__isnull=False, contenido__gt=0, unidad_contenido__isnull=False),
                name="ck_producto_contenido_coherente",
            ),
            models.CheckConstraint(
                condition=Q(unidad_contenido__isnull=True)
                | Q(unidad_contenido__in=UnidadContenido.values),
                name="ck_producto_unidad_contenido",
            ),
            models.CheckConstraint(
                condition=Q(costo__isnull=True) | Q(costo__gte=0), name="ck_producto_costo"
            ),
        ]
        indexes = [models.Index(fields=["codigo_barras"], name="ix_producto_codigo")]

    def __str__(self):
        return f"{self.nombre} ({self.codigo_barras})"

    @property
    def stock_bajo(self):
        return self.stock_actual <= self.stock_minimo

    @property
    def contenido_cifra(self):
        """350.00 -> «350»; 1.50 -> «1,5» (coma decimal, como en Chile)."""
        if self.contenido is None:
            return ""
        numero = Decimal(self.contenido)
        if numero == numero.to_integral_value():
            return f"{int(numero)}"
        return f"{numero.normalize():f}".replace(".", ",")

    @property
    def contenido_texto(self):
        """«350 ml», «1,5 L», «6 unidades», «1 unidad»; vacío si no tiene contenido."""
        if self.contenido is None or not self.unidad_contenido:
            return ""
        cifra = self.contenido_cifra
        if self.unidad_contenido == UnidadContenido.UNIDADES:
            return f"{cifra} unidad" if Decimal(self.contenido) == 1 else f"{cifra} unidades"
        return f"{cifra} {self.unidad_contenido}"


class TipoMovimiento(models.TextChoices):
    ENTRADA = "entrada", "Entrada"
    SALIDA = "salida", "Salida"
    AJUSTE = "ajuste", "Ajuste"


class MotivoAjuste(models.TextChoices):
    """
    Motivos de un movimiento tipo `ajuste`. Lista cerrada (ck_movimiento_stock_motivo):
    cada motivo nuevo es una migración.
    """

    DIFERENCIA_INVENTARIO = "Diferencia de inventario", "Diferencia de inventario"
    PRODUCTO_DANADO = "Producto dañado", "Producto dañado"
    PRODUCTO_VENCIDO = "Producto vencido", "Producto vencido"
    CORRECCION_ADMINISTRATIVA = "Corrección administrativa", "Corrección administrativa"
    # Los dos siguientes los genera la caja; el formulario de ajuste no los ofrece.
    VENTA_SIN_STOCK = "Venta sin stock registrado", "Venta sin stock registrado"
    ALTA_RAPIDA = "Alta rápida en caja", "Alta rápida en caja"


MOTIVOS_AJUSTE_MANUAL = [
    MotivoAjuste.DIFERENCIA_INVENTARIO,
    MotivoAjuste.PRODUCTO_DANADO,
    MotivoAjuste.PRODUCTO_VENCIDO,
    MotivoAjuste.CORRECCION_ADMINISTRATIVA,
]


class MovimientoStock(ModeloDeAlmacen):
    """
    Bitácora: toda variación de Producto.stock_actual genera un registro.
    `entrada` y `salida` llevan cantidad positiva (el tipo es el signo); sólo
    `ajuste` lleva signo y motivo. Una `salida` con id_venta es una venta; una
    `entrada` con id_venta es la restitución por anulación.
    """

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
    # Quién hizo el movimiento (1.4.3). Obligatorio: sólo la capa de servicios crea
    # movimientos y siempre sabe quién opera.
    id_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario",
        related_name="movimientos_stock",
        db_index=False,
    )
    tipo = models.CharField(max_length=10, choices=TipoMovimiento.choices)
    cantidad = models.IntegerField()
    motivo = models.CharField(
        max_length=40, choices=MotivoAjuste.choices, null=True, blank=True
    )
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
            ),
            # En los dos sentidos: entrada/salida positivas y sin motivo;
            # ajuste distinto de cero y con motivo.
            models.CheckConstraint(
                condition=Q(
                    tipo__in=[TipoMovimiento.ENTRADA, TipoMovimiento.SALIDA],
                    cantidad__gt=0,
                    motivo__isnull=True,
                )
                | (Q(tipo=TipoMovimiento.AJUSTE, motivo__isnull=False) & ~Q(cantidad=0)),
                name="ck_movimiento_stock_cantidad",
            ),
            models.CheckConstraint(
                condition=Q(motivo__isnull=True) | Q(motivo__in=MotivoAjuste.values),
                name="ck_movimiento_stock_motivo",
            ),
        ]
        indexes = [
            models.Index(fields=["id_producto", "fecha_hora"], name="ix_mov_prod_fecha"),
            # Ajuste de rendimiento acordado el 2026-10-14 (no está en la Figura 7):
            # sin él, todo listado de movimientos por almacén recorre la tabla completa.
            models.Index(fields=["id_almacen", "fecha_hora"], name="ix_mov_almacen_fecha"),
        ]

    def __str__(self):
        return f"{self.tipo} x{self.cantidad} - producto #{self.id_producto_id}"
