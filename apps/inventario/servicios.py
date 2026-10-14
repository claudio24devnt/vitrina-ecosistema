"""
Reglas de negocio de Productos e Inventario (CU-01).

Única puerta para cambiar `Producto.stock_actual`: toda variación deja su
MovimientoStock, y todo registro nace en el mismo almacén que el producto
(o la venta) al que pertenece.
"""

from django.db import IntegrityError, transaction

from apps.almacenes.errores import ReglaDeNegocioError

from .models import Categoria, MovimientoStock, Producto, TipoMovimiento


class CodigoDuplicadoError(ReglaDeNegocioError):
    """El código ya existe en este almacén: el flujo ofrece sumar stock (CU-01 2a)."""

    def __init__(self, producto):
        self.producto = producto
        donde = f" en {producto.id_categoria.nombre}" if producto.id_categoria_id else ""
        super().__init__(
            f"Ese código de barras ya está registrado{donde}: «{producto.nombre}». "
            "Puedes sumarle stock en vez de crearlo de nuevo."
        )


def _exigir_mismo_almacen(almacen, *registros):
    id_almacen = getattr(almacen, "pk", almacen)
    for registro in registros:
        if registro is not None and registro.id_almacen_id != id_almacen:
            # No debería ocurrir desde la interfaz: indica un error de programación
            # o un intento de operar sobre datos de otro almacén.
            raise ReglaDeNegocioError("Ese registro no pertenece a tu almacén.")


def buscar_por_codigo(almacen, codigo):
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    return (
        Producto.objects.del_almacen(almacen)
        .select_related("id_categoria")
        .filter(codigo_barras=codigo)
        .first()
    )


def registrar_movimiento(*, producto, tipo, cantidad, venta=None):
    """
    Crea el MovimientoStock con el almacén del producto. No toca stock_actual:
    lo llaman los servicios que ya actualizaron el stock dentro de su transacción.
    """
    _exigir_mismo_almacen(producto.id_almacen_id, venta)
    return MovimientoStock.objects.del_almacen(producto.id_almacen_id).create(
        id_producto=producto, id_venta=venta, tipo=tipo, cantidad=cantidad
    )


def registrar_entrada_stock(*, almacen, producto, cantidad):
    """Suma stock y deja el movimiento de entrada, en una sola transacción."""
    _exigir_mismo_almacen(almacen, producto)
    if cantidad is None or cantidad <= 0:
        raise ReglaDeNegocioError("La cantidad a sumar debe ser mayor que cero.")

    with transaction.atomic():
        bloqueado = (
            Producto.objects.del_almacen(almacen).select_for_update().get(pk=producto.pk)
        )
        bloqueado.stock_actual += cantidad
        bloqueado.save(update_fields=["stock_actual"])
        registrar_movimiento(
            producto=bloqueado, tipo=TipoMovimiento.ENTRADA, cantidad=cantidad
        )

    producto.stock_actual = bloqueado.stock_actual
    return producto


def registrar_producto(
    *, almacen, codigo_barras, nombre, precio, categoria=None, stock_minimo=0, stock_inicial=0
):
    """
    CU-01: alta de producto. Si el código ya existe en el almacén lanza
    CodigoDuplicadoError (con el producto existente) en vez de duplicarlo.
    """
    codigo_barras = (codigo_barras or "").strip()
    _exigir_mismo_almacen(almacen, categoria)
    existente = buscar_por_codigo(almacen, codigo_barras)
    if existente:
        raise CodigoDuplicadoError(existente)
    if stock_inicial < 0:
        raise ReglaDeNegocioError("El stock inicial no puede ser negativo.")

    try:
        with transaction.atomic():
            producto = Producto.objects.del_almacen(almacen).create(
                codigo_barras=codigo_barras,
                nombre=nombre.strip(),
                precio=precio,
                id_categoria=categoria,
                stock_minimo=stock_minimo,
                stock_actual=0,
            )
            if stock_inicial > 0:
                registrar_entrada_stock(
                    almacen=almacen, producto=producto, cantidad=stock_inicial
                )
    except IntegrityError:
        # Otro usuario registró el mismo código entre la búsqueda y el INSERT.
        existente = buscar_por_codigo(almacen, codigo_barras)
        if existente:
            raise CodigoDuplicadoError(existente) from None
        raise
    return producto


def actualizar_producto(
    *, almacen, producto, codigo_barras, nombre, precio, categoria, stock_minimo
):
    """Edita los datos del producto. El stock nunca se edita aquí: pasa por movimientos."""
    _exigir_mismo_almacen(almacen, producto, categoria)
    codigo_barras = (codigo_barras or "").strip()
    otro = buscar_por_codigo(almacen, codigo_barras)
    if otro and otro.pk != producto.pk:
        raise CodigoDuplicadoError(otro)

    producto.codigo_barras = codigo_barras
    producto.nombre = nombre.strip()
    producto.precio = precio
    producto.id_categoria = categoria
    producto.stock_minimo = stock_minimo
    producto.save(
        update_fields=["codigo_barras", "nombre", "precio", "id_categoria", "stock_minimo"]
    )
    return producto


def crear_categoria(*, almacen, nombre):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ReglaDeNegocioError("Escribe un nombre para la categoría.")
    if Categoria.objects.del_almacen(almacen).filter(nombre__iexact=nombre).exists():
        raise ReglaDeNegocioError(f"Ya existe la categoría «{nombre}».")
    return Categoria.objects.del_almacen(almacen).create(nombre=nombre)
