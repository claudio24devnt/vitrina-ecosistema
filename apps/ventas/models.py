from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Length, Now, Trim
from django.db.models.lookups import GreaterThanOrEqual
from django.utils import timezone

from apps.almacenes.aislamiento import ModeloDeAlmacen


class EstadoVenta(models.TextChoices):
    VIGENTE = "vigente", "Vigente"
    ANULADA = "anulada", "Anulada"


class MedioPago(models.TextChoices):
    EFECTIVO = "efectivo", "Efectivo"
    DEBITO = "debito", "Débito"
    CREDITO = "credito", "Crédito"
    TRANSFERENCIA = "transferencia", "Transferencia"


MOTIVO_ANULACION_LARGO_MINIMO = 5


class Venta(ModeloDeAlmacen):
    """
    Una venta no se borra al anularse: cambia a `anulada`, guarda quién, cuándo y por
    qué, y la capa de servicios genera los movimientos de stock compensatorios.
    """

    id_venta = models.BigAutoField(primary_key=True, db_column="id_venta")
    id_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario",
        related_name="ventas",
        db_index=False,
    )
    # fecha_hora = confirmación; hora_inicio = apertura (indicador de tiempo de registro).
    fecha_hora = models.DateTimeField(default=timezone.now, db_default=Now())
    hora_inicio = models.DateTimeField(null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=0)
    medio_pago = models.CharField(max_length=20, choices=MedioPago.choices)
    estado = models.CharField(
        max_length=10,
        choices=EstadoVenta.choices,
        default=EstadoVenta.VIGENTE,
        db_default=EstadoVenta.VIGENTE,
    )
    id_usuario_anulacion = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario_anulacion",
        related_name="ventas_anuladas",
        null=True,
        blank=True,
        db_index=False,
    )
    motivo_anulacion = models.CharField(max_length=200, null=True, blank=True)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "venta"
        default_manager_name = "sin_aislamiento"
        ordering = ["-fecha_hora"]
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoVenta.values), name="ck_venta_estado"
            ),
            # La auditoría de anulación no puede mentir en ninguno de los dos sentidos:
            # anulada => los tres campos llenos (motivo con contenido real);
            # no anulada => los tres vacíos.
            models.CheckConstraint(
                condition=(
                    Q(
                        estado=EstadoVenta.ANULADA,
                        id_usuario_anulacion__isnull=False,
                        fecha_anulacion__isnull=False,
                        motivo_anulacion__isnull=False,
                    )
                    & GreaterThanOrEqual(
                        Length(Trim("motivo_anulacion")), MOTIVO_ANULACION_LARGO_MINIMO
                    )
                )
                | (
                    ~Q(estado=EstadoVenta.ANULADA)
                    & Q(
                        id_usuario_anulacion__isnull=True,
                        fecha_anulacion__isnull=True,
                        motivo_anulacion__isnull=True,
                    )
                ),
                name="ck_venta_anulacion_coherente",
            ),
            models.CheckConstraint(
                condition=Q(fecha_anulacion__isnull=True)
                | Q(fecha_anulacion__gte=F("fecha_hora")),
                name="ck_venta_anulacion_posterior",
            ),
        ]
        indexes = [
            models.Index(fields=["id_almacen", "fecha_hora"], name="ix_venta_fecha"),
            models.Index(
                fields=["id_almacen", "fecha_anulacion"],
                name="ix_venta_anuladas",
                condition=Q(estado=EstadoVenta.ANULADA),
            ),
        ]

    def __str__(self):
        return f"Venta #{self.id_venta} - {self.estado}"


class DetalleVenta(ModeloDeAlmacen):
    """id_almacen es redundante con el de la venta a propósito (filtro uniforme);
    la capa de servicios garantiza que coincidan."""

    id_detalle = models.BigAutoField(primary_key=True, db_column="id_detalle")
    id_venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        db_column="id_venta",
        related_name="detalles",
        db_index=False,
    )
    id_producto = models.ForeignKey(
        "inventario.Producto",
        on_delete=models.PROTECT,
        db_column="id_producto",
        related_name="detalles_venta",
        db_index=False,
    )
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=0)

    class Meta:
        db_table = "detalle_venta"
        default_manager_name = "sin_aislamiento"
        verbose_name = "detalle de venta"
        verbose_name_plural = "detalles de venta"
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="ck_detalle_venta_cantidad"
            )
        ]
        indexes = [models.Index(fields=["id_venta"], name="ix_detalle_venta")]

    def __str__(self):
        return f"{self.cantidad} x producto #{self.id_producto_id} (venta #{self.id_venta_id})"
