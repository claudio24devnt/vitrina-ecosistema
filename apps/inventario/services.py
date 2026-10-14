from django.db import transaction

from .models import MovimientoStock, Producto, TipoMovimiento


def registrar_entrada_stock(*, producto: Producto, cantidad: int) -> Producto:
    """
    Aumenta Producto.stock_actual y deja el MovimientoStock de auditoría
    correspondiente, todo dentro de una transacción atómica.

    Usado tanto para el stock inicial de un producto nuevo como para
    sumar stock a un producto ya existente (mismo código de barras).
    """
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que cero")

    with transaction.atomic():
        producto_bloqueado = Producto.objects.select_for_update().get(pk=producto.pk)
        producto_bloqueado.stock_actual += cantidad
        producto_bloqueado.save(update_fields=["stock_actual"])
        MovimientoStock.objects.create(
            id_producto=producto_bloqueado,
            tipo=TipoMovimiento.ENTRADA,
            cantidad=cantidad,
        )

    producto.refresh_from_db(fields=["stock_actual"])
    return producto


@transaction.atomic
def crear_producto_con_stock_inicial(*, datos_producto: dict, stock_inicial: int) -> Producto:
    """Crea el producto y, si trae stock inicial > 0, genera el MovimientoStock de entrada."""
    producto = Producto.objects.create(**datos_producto, stock_actual=0)
    if stock_inicial > 0:
        registrar_entrada_stock(producto=producto, cantidad=stock_inicial)
    return producto
