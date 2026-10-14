from django.conf import settings
from django.db import models


class EstadoVenta(models.TextChoices):
    VIGENTE = "vigente", "Vigente"
    ANULADA = "anulada", "Anulada"


class MedioPago(models.TextChoices):
    EFECTIVO = "efectivo", "Efectivo"
    DEBITO = "debito", "Débito"
    CREDITO = "credito", "Crédito"
    TRANSFERENCIA = "transferencia", "Transferencia"


class Venta(models.Model):
    """
    Modelo de datos para el modulo Ventas (logica de negocio: fase 5).
    """

    id_venta = models.AutoField(primary_key=True)
    id_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario",
        related_name="ventas",
    )
    fecha_hora = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    medio_pago = models.CharField(max_length=20, choices=MedioPago.choices)
    estado = models.CharField(
        max_length=10, choices=EstadoVenta.choices, default=EstadoVenta.VIGENTE
    )

    class Meta:
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        ordering = ["-fecha_hora"]

    def __str__(self):
        return f"Venta #{self.id_venta} - {self.estado}"


class DetalleVenta(models.Model):
    id_detalle = models.AutoField(primary_key=True)
    id_venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        db_column="id_venta",
        related_name="detalles",
    )
    id_producto = models.ForeignKey(
        "inventario.Producto",
        on_delete=models.PROTECT,
        db_column="id_producto",
        related_name="detalles_venta",
    )
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "detalle de venta"
        verbose_name_plural = "detalles de venta"

    def __str__(self):
        return f"{self.cantidad} x {self.id_producto.nombre} (venta #{self.id_venta_id})"
