from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento

from .models import DetalleVenta, EstadoVenta, Venta


class VentaError(Exception):
    """Regla de negocio violada al registrar o anular una venta (mensaje para el usuario)."""


def _agrupar_items(items):
    """Suma cantidades si el mismo producto viene más de una vez (ej. escaneado dos veces)."""
    cantidades = {}
    for id_producto, cantidad in items:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise VentaError("Todas las cantidades deben ser mayores que cero.")
        cantidades[int(id_producto)] = cantidades.get(int(id_producto), 0) + cantidad
    return cantidades


def registrar_venta(*, usuario, items, medio_pago) -> Venta:
    """
    Registra una venta y descuenta el stock de cada producto, todo en una
    transacción atómica: si algún producto no tiene stock suficiente no se
    guarda nada.

    `items` es una lista de pares (id_producto, cantidad). El precio unitario
    se toma del producto al momento de la venta (no se confía en el cliente).
    Cada descuento de stock deja un MovimientoStock de salida ligado a la venta.
    """
    cantidades = _agrupar_items(items)
    if not cantidades:
        raise VentaError("La venta no tiene productos.")

    with transaction.atomic():
        # Bloqueo ordenado por PK para evitar deadlocks entre ventas simultáneas.
        productos = {
            p.pk: p
            for p in Producto.objects.select_for_update()
            .filter(pk__in=cantidades.keys())
            .order_by("pk")
        }
        faltantes = set(cantidades) - set(productos)
        if faltantes:
            raise VentaError("Uno o más productos de la venta ya no existen.")

        sin_stock = [
            f"«{productos[pk].nombre}» (pedido {cantidad}, "
            f"disponible {productos[pk].stock_actual})"
            for pk, cantidad in cantidades.items()
            if productos[pk].stock_actual < cantidad
        ]
        if sin_stock:
            raise VentaError("Stock insuficiente: " + "; ".join(sin_stock) + ".")

        venta = Venta.objects.create(
            id_usuario=usuario, total=Decimal("0"), medio_pago=medio_pago
        )
        total = Decimal("0")
        for pk, cantidad in cantidades.items():
            producto = productos[pk]
            subtotal = producto.precio * cantidad
            total += subtotal
            DetalleVenta.objects.create(
                id_venta=venta,
                id_producto=producto,
                cantidad=cantidad,
                precio_unitario=producto.precio,
                subtotal=subtotal,
            )
            producto.stock_actual -= cantidad
            producto.save(update_fields=["stock_actual"])
            MovimientoStock.objects.create(
                id_producto=producto,
                tipo=TipoMovimiento.SALIDA,
                cantidad=cantidad,
                id_venta=venta,
            )

        venta.total = total
        venta.save(update_fields=["total"])

    return venta


def plazo_anulacion_vencido(venta: Venta) -> bool:
    limite = venta.fecha_hora + timedelta(minutes=settings.PLAZO_ANULACION_VENTA_MINUTOS)
    return timezone.now() > limite


def anular_venta(*, venta: Venta, usuario) -> Venta:
    """
    Anula una venta vigente y repone el stock de sus productos.

    Reglas: sólo un administrador puede anular, y sólo dentro del plazo
    configurado (settings.PLAZO_ANULACION_VENTA_MINUTOS). La reposición de
    stock deja un MovimientoStock de entrada ligado a la venta anulada.
    """
    if not usuario.es_admin:
        raise VentaError("Sólo un administrador puede anular ventas.")

    with transaction.atomic():
        venta = Venta.objects.select_for_update().get(pk=venta.pk)
        if venta.estado != EstadoVenta.VIGENTE:
            raise VentaError(f"La venta #{venta.id_venta} ya está anulada.")
        if plazo_anulacion_vencido(venta):
            raise VentaError(
                f"La venta #{venta.id_venta} ya no se puede anular: pasaron más de "
                f"{settings.PLAZO_ANULACION_VENTA_MINUTOS} minutos desde que se registró."
            )

        detalles = list(venta.detalles.order_by("id_producto_id"))
        productos = {
            p.pk: p
            for p in Producto.objects.select_for_update()
            .filter(pk__in=[d.id_producto_id for d in detalles])
            .order_by("pk")
        }
        for detalle in detalles:
            producto = productos[detalle.id_producto_id]
            producto.stock_actual += detalle.cantidad
            producto.save(update_fields=["stock_actual"])
            MovimientoStock.objects.create(
                id_producto=producto,
                tipo=TipoMovimiento.ENTRADA,
                cantidad=detalle.cantidad,
                id_venta=venta,
            )

        venta.estado = EstadoVenta.ANULADA
        venta.save(update_fields=["estado"])

    return venta
