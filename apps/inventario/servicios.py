"""
Reglas de negocio de Productos e Inventario (CU-01 y ajustes de inventario).

Única puerta para cambiar `Producto.stock_actual`: toda variación deja su
MovimientoStock con el usuario que la hizo, y todo registro nace en el mismo
almacén que el producto, la venta y el usuario a los que se refiere.
"""

from django.db import IntegrityError, transaction
from django.db.models import F

from apps.almacenes.errores import ReglaDeNegocioError

from .models import (
    MOTIVOS_AJUSTE_MANUAL,
    Categoria,
    MovimientoStock,
    Producto,
    TipoMovimiento,
)


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


def productos_con_stock_bajo(almacen):
    """
    Productos con stock en o bajo el mínimo (`Producto.stock_bajo`). Estar en el mínimo
    ya cuenta: es el momento de reponer. Fuente única del umbral para el panel, el
    inventario y la alerta diaria (CU-05).
    """
    return Producto.objects.del_almacen(almacen).filter(stock_actual__lte=F("stock_minimo"))


def registrar_movimiento(*, producto, tipo, cantidad, usuario, venta=None, motivo=None):
    """
    Crea el MovimientoStock con el almacén del producto. No toca stock_actual:
    lo llaman los servicios que ya actualizaron el stock dentro de su transacción.
    El usuario y la venta deben ser del mismo almacén que el producto.
    """
    _exigir_mismo_almacen(producto.id_almacen_id, venta, usuario)
    return MovimientoStock.objects.del_almacen(producto.id_almacen_id).create(
        id_producto=producto,
        id_venta=venta,
        id_usuario=usuario,
        tipo=tipo,
        cantidad=cantidad,
        motivo=motivo,
    )


def bloquear_productos(almacen, ids):
    """SELECT ... FOR UPDATE de los productos, en orden de PK para evitar deadlocks."""
    return {
        p.pk: p
        for p in Producto.objects.del_almacen(almacen)
        .select_for_update()
        .filter(pk__in=ids)
        .order_by("pk")
    }


def aplicar_ajuste(*, producto, diferencia, motivo, usuario, venta=None):
    """
    Suma (o resta) `diferencia` al stock de un producto YA bloqueado y deja el
    movimiento de ajuste con su motivo. Debe llamarse dentro de una transacción.
    Un solo camino para el ajuste manual y para la caja (CU-02 6a y alta rápida).
    """
    if diferencia == 0:
        raise ReglaDeNegocioError("No hay diferencia que ajustar.")
    if producto.stock_actual + diferencia < 0:
        raise ReglaDeNegocioError(
            f"«{producto.nombre}» quedaría con stock negativo. Revisa la cantidad."
        )
    producto.stock_actual += diferencia
    producto.save(update_fields=["stock_actual"])
    return registrar_movimiento(
        producto=producto,
        tipo=TipoMovimiento.AJUSTE,
        cantidad=diferencia,
        motivo=motivo,
        usuario=usuario,
        venta=venta,
    )


def registrar_ajuste_por_conteo(*, almacen, producto, cantidad_contada, motivo, usuario):
    """
    Ajuste de inventario del administrador: el stock pasa a `cantidad_contada` y la
    diferencia (positiva o negativa) queda como ajuste con motivo. Sólo acepta los
    motivos manuales: los de la caja no se eligen a mano (indicador de exactitud).
    """
    _exigir_mismo_almacen(almacen, producto, usuario)
    if motivo not in MOTIVOS_AJUSTE_MANUAL:
        raise ReglaDeNegocioError("Elige un motivo de la lista.")
    if cantidad_contada is None or cantidad_contada < 0:
        raise ReglaDeNegocioError("La cantidad contada no puede ser negativa.")

    with transaction.atomic():
        bloqueado = bloquear_productos(almacen, [producto.pk])[producto.pk]
        movimiento = aplicar_ajuste(
            producto=bloqueado,
            diferencia=cantidad_contada - bloqueado.stock_actual,
            motivo=motivo,
            usuario=usuario,
        )
    producto.stock_actual = bloqueado.stock_actual
    return movimiento


def registrar_entrada_stock(*, almacen, producto, cantidad, usuario):
    """Suma stock y deja el movimiento de entrada, en una sola transacción."""
    _exigir_mismo_almacen(almacen, producto, usuario)
    if cantidad is None or cantidad <= 0:
        raise ReglaDeNegocioError("La cantidad a sumar debe ser mayor que cero.")

    with transaction.atomic():
        bloqueado = (
            Producto.objects.del_almacen(almacen).select_for_update().get(pk=producto.pk)
        )
        bloqueado.stock_actual += cantidad
        bloqueado.save(update_fields=["stock_actual"])
        registrar_movimiento(
            producto=bloqueado, tipo=TipoMovimiento.ENTRADA, cantidad=cantidad, usuario=usuario
        )

    producto.stock_actual = bloqueado.stock_actual
    return producto


def registrar_producto(
    *,
    almacen,
    usuario,
    codigo_barras,
    nombre,
    precio,
    categoria=None,
    stock_minimo=0,
    stock_inicial=0,
):
    """
    CU-01: alta de producto. También la usa la alta rápida de la caja (CU-02 2a), que
    llega sin categoría ni stock. Si el código ya existe en el almacén lanza
    CodigoDuplicadoError (con el producto existente) en vez de duplicarlo.
    """
    codigo_barras = (codigo_barras or "").strip()
    nombre = (nombre or "").strip()
    _exigir_mismo_almacen(almacen, categoria, usuario)
    if not codigo_barras or not nombre:
        raise ReglaDeNegocioError("Faltan el código de barras o el nombre.")
    if precio is None or precio < 0:
        raise ReglaDeNegocioError("El precio no puede ser negativo.")
    existente = buscar_por_codigo(almacen, codigo_barras)
    if existente:
        raise CodigoDuplicadoError(existente)
    if stock_inicial < 0:
        raise ReglaDeNegocioError("El stock inicial no puede ser negativo.")

    try:
        with transaction.atomic():
            producto = Producto.objects.del_almacen(almacen).create(
                codigo_barras=codigo_barras,
                nombre=nombre,
                precio=precio,
                id_categoria=categoria,
                stock_minimo=stock_minimo,
                stock_actual=0,
                id_usuario_creacion=usuario,
            )
            if stock_inicial > 0:
                registrar_entrada_stock(
                    almacen=almacen, producto=producto, cantidad=stock_inicial, usuario=usuario
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
