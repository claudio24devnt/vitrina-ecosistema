"""
Reglas de negocio de Productos e Inventario (CU-01 y ajustes de inventario).

Única puerta para cambiar `Producto.stock_actual`: toda variación deja su
MovimientoStock con el usuario que la hizo, y todo registro nace en el mismo
almacén que el producto, la venta y el usuario a los que se refiere.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Q

from apps.almacenes.errores import ReglaDeNegocioError

from .models import (
    MOTIVOS_AJUSTE_MANUAL,
    Categoria,
    MovimientoStock,
    Producto,
    TipoMovimiento,
    UnidadContenido,
)

# Valor del filtro de categoría del inventario para los productos sin categoría (los de
# la alta rápida de la caja quedan así hasta que el administrador la completa).
SIN_CATEGORIA = "sin"

FILTROS_STOCK = ("todos", "bajo", "sin")

# Orden del inventario. Siempre termina en la PK: orden total, ningún producto salta
# entre páginas.
ORDENES_INVENTARIO = {
    "nombre": ("nombre", "pk"),
    "stock": ("stock_actual", "nombre", "pk"),
    "precio": ("precio", "nombre", "pk"),
}

MENSAJE_DOS_CATEGORIAS = (
    "Elige una categoría de la lista o escribe una nueva, pero no las dos a la vez."
)

LARGO_DESCRIPCION = 300
# NUMERIC(8,2): hasta 999.999,99.
CONTENIDO_MAXIMO = Decimal("999999.99")
# NUMERIC(10,0), igual que el precio.
COSTO_MAXIMO = Decimal("9999999999")


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


def registrar_entrada_stock(*, almacen, producto, cantidad, usuario, costo=None):
    """
    Suma stock y deja el movimiento de entrada, en una sola transacción. `costo` (opcional)
    es el costo por unidad de lo que llegó: pasa a ser el costo del producto desde ahora.
    Las ventas ya hechas conservan el suyo (detalle_venta.costo_unitario).
    """
    _exigir_mismo_almacen(almacen, producto, usuario)
    if cantidad is None or cantidad <= 0:
        raise ReglaDeNegocioError("La cantidad a sumar debe ser mayor que cero.")
    costo = validar_costo(costo)

    with transaction.atomic():
        bloqueado = (
            Producto.objects.del_almacen(almacen).select_for_update().get(pk=producto.pk)
        )
        bloqueado.stock_actual += cantidad
        campos = ["stock_actual"]
        if costo is not None:
            bloqueado.costo = costo
            campos.append("costo")
        bloqueado.save(update_fields=campos)
        registrar_movimiento(
            producto=bloqueado, tipo=TipoMovimiento.ENTRADA, cantidad=cantidad, usuario=usuario
        )

    producto.stock_actual = bloqueado.stock_actual
    producto.costo = bloqueado.costo
    return producto


def validar_costo(costo):
    """
    Costo por unidad en pesos: opcional (None = no se sabe; nunca se toma como cero), sin
    decimales y no negativo. Puede ser mayor que el precio: vender bajo el costo es una
    decisión del almacén (una oferta), no un error.
    """
    if costo is None or costo == "":
        return None
    costo = Decimal(costo)
    if costo < 0:
        raise ReglaDeNegocioError("El costo no puede ser negativo.")
    if costo != costo.to_integral_value():
        raise ReglaDeNegocioError("El costo va en pesos, sin decimales.")
    if costo > COSTO_MAXIMO:
        raise ReglaDeNegocioError("El costo es demasiado alto. Revisa la cifra.")
    return costo


def registrar_producto(
    *,
    almacen,
    usuario,
    codigo_barras,
    nombre,
    precio,
    categoria=None,
    categoria_nueva=None,
    stock_minimo=0,
    stock_inicial=0,
    descripcion=None,
    contenido=None,
    unidad_contenido=None,
    costo=None,
):
    """
    CU-01: alta de producto. También la usa la alta rápida de la caja (CU-02 2a), que
    llega sin categoría, stock ni datos descriptivos. Si el código ya existe en el
    almacén lanza CodigoDuplicadoError (con el producto existente) en vez de duplicarlo.

    `categoria_nueva` (texto) crea la categoría en la misma transacción del alta: si el
    alta falla, la categoría no queda. Si ya existe una con ese nombre se usa esa. El
    producto devuelto lleva `categoria_creada` (True si se creó una categoría nueva).
    """
    codigo_barras = (codigo_barras or "").strip()
    nombre = (nombre or "").strip()
    _exigir_mismo_almacen(almacen, categoria, usuario)
    if not codigo_barras or not nombre:
        raise ReglaDeNegocioError("Faltan el código de barras o el nombre.")
    if precio is None or precio < 0:
        raise ReglaDeNegocioError("El precio no puede ser negativo.")
    descriptivos = _validar_descriptivos(descripcion, contenido, unidad_contenido)
    costo = validar_costo(costo)
    categoria_nueva = _validar_eleccion_de_categoria(categoria, categoria_nueva)
    existente = buscar_por_codigo(almacen, codigo_barras)
    if existente:
        raise CodigoDuplicadoError(existente)
    if stock_inicial < 0:
        raise ReglaDeNegocioError("El stock inicial no puede ser negativo.")

    try:
        with transaction.atomic():
            creada = False
            if categoria_nueva:
                categoria, creada = obtener_o_crear_categoria(
                    almacen=almacen, nombre=categoria_nueva
                )
            producto = Producto.objects.del_almacen(almacen).create(
                codigo_barras=codigo_barras,
                nombre=nombre,
                precio=precio,
                id_categoria=categoria,
                stock_minimo=stock_minimo,
                stock_actual=0,
                id_usuario_creacion=usuario,
                costo=costo,
                **descriptivos,
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
    producto.categoria_creada = creada
    return producto


def actualizar_producto(
    *,
    almacen,
    producto,
    codigo_barras,
    nombre,
    precio,
    categoria,
    stock_minimo,
    categoria_nueva=None,
    descripcion=None,
    contenido=None,
    unidad_contenido=None,
    costo=None,
):
    """
    Edita los datos del producto. El stock nunca se edita aquí: pasa por movimientos.
    El formulario envía todos los campos: `descripcion`/`contenido`/`costo` en None los
    borran. Cambiar el costo no toca las ventas ya hechas (guardan el suyo).
    `categoria_nueva` funciona igual que en el alta (misma transacción, reutiliza la
    existente); el producto devuelto lleva `categoria_creada`.
    """
    _exigir_mismo_almacen(almacen, producto, categoria)
    codigo_barras = (codigo_barras or "").strip()
    nombre = (nombre or "").strip()
    if not codigo_barras or not nombre:
        raise ReglaDeNegocioError("Faltan el código de barras o el nombre.")
    descriptivos = _validar_descriptivos(descripcion, contenido, unidad_contenido)
    costo = validar_costo(costo)
    categoria_nueva = _validar_eleccion_de_categoria(categoria, categoria_nueva)
    otro = buscar_por_codigo(almacen, codigo_barras)
    if otro and otro.pk != producto.pk:
        raise CodigoDuplicadoError(otro)

    with transaction.atomic():
        creada = False
        if categoria_nueva:
            categoria, creada = obtener_o_crear_categoria(
                almacen=almacen, nombre=categoria_nueva
            )
        producto.codigo_barras = codigo_barras
        producto.nombre = nombre
        producto.precio = precio
        producto.id_categoria = categoria
        producto.stock_minimo = stock_minimo
        producto.costo = costo
        for campo, valor in descriptivos.items():
            setattr(producto, campo, valor)
        producto.save(
            update_fields=[
                "codigo_barras",
                "nombre",
                "precio",
                "id_categoria",
                "stock_minimo",
                "costo",
                *descriptivos,
            ]
        )
    producto.categoria_creada = creada
    return producto


def _validar_descriptivos(descripcion, contenido, unidad_contenido):
    """
    Descripción y contenido son opcionales y sólo descriptivos (no tocan stock). Vacío
    queda NULL, nunca texto vacío. Contenido y unidad van juntos
    (ck_producto_contenido_coherente); se revisa aquí para dar un mensaje claro.
    """
    descripcion = (descripcion or "").strip() or None
    if descripcion and len(descripcion) > LARGO_DESCRIPCION:
        raise ReglaDeNegocioError(
            f"La descripción puede tener hasta {LARGO_DESCRIPCION} caracteres."
        )
    unidad_contenido = unidad_contenido or None
    if (contenido is None) != (unidad_contenido is None):
        raise ReglaDeNegocioError(
            "Para el contenido escribe la cantidad y elige la unidad (por ejemplo, 350 ml)."
        )
    if contenido is not None:
        contenido = Decimal(contenido)
        if contenido <= 0 or contenido > CONTENIDO_MAXIMO:
            raise ReglaDeNegocioError(
                "El contenido debe ser mayor que cero y menor que un millón."
            )
        if contenido != contenido.quantize(Decimal("0.01")):
            raise ReglaDeNegocioError("El contenido admite hasta dos decimales.")
        if unidad_contenido not in UnidadContenido.values:
            raise ReglaDeNegocioError("Elige una unidad de la lista.")
    return {
        "descripcion": descripcion,
        "contenido": contenido,
        "unidad_contenido": unidad_contenido,
    }


def _validar_eleccion_de_categoria(categoria, categoria_nueva):
    categoria_nueva = normalizar_nombre_categoria(categoria_nueva)
    if categoria is not None and categoria_nueva:
        raise ReglaDeNegocioError(MENSAJE_DOS_CATEGORIAS)
    return categoria_nueva


def normalizar_nombre_categoria(nombre):
    """Sin espacios al borde ni repetidos: «  Bebidas   y jugos » -> «Bebidas y jugos»."""
    return " ".join((nombre or "").split())


def buscar_categoria(almacen, nombre):
    """La categoría del almacén con ese nombre, sin distinguir mayúsculas ni espacios."""
    nombre = normalizar_nombre_categoria(nombre)
    if not nombre:
        return None
    return Categoria.objects.del_almacen(almacen).filter(nombre__iexact=nombre).first()


def crear_categoria(*, almacen, nombre):
    nombre = normalizar_nombre_categoria(nombre)
    if not nombre:
        raise ReglaDeNegocioError("Escribe un nombre para la categoría.")
    if buscar_categoria(almacen, nombre):
        raise ReglaDeNegocioError(f"Ya existe la categoría «{nombre}».")
    return Categoria.objects.del_almacen(almacen).create(nombre=nombre)


def obtener_o_crear_categoria(*, almacen, nombre):
    """
    Para el formulario del producto: si la categoría ya existe (sin distinguir
    mayúsculas ni espacios) se usa esa en vez de fallar; si no, se crea. Devuelve
    (categoría, creada). Pensada para correr dentro de la transacción del alta.
    """
    existente = buscar_categoria(almacen, nombre)
    if existente:
        return existente, False
    try:
        # Punto de guardado: si otro usuario la creó recién (uq_categoria), se usa la
        # suya sin abortar la transacción del alta.
        with transaction.atomic():
            return crear_categoria(almacen=almacen, nombre=nombre), True
    except IntegrityError:
        existente = buscar_categoria(almacen, nombre)
        if existente:
            return existente, False
        raise


def filtrar_productos(
    almacen, *, texto="", categoria=None, stock="todos", orden="nombre", sin_costo=False
):
    """
    Inventario con búsqueda y filtros (ambos roles). `texto` busca cada palabra en el
    nombre, el código de barras o la descripción (todas las palabras deben aparecer,
    cada una en cualquiera de los tres). `categoria`: None (todas), SIN_CATEGORIA o una
    Categoria del almacén. `stock`: "todos", "bajo" (la misma regla de la alerta,
    `productos_con_stock_bajo`) o "sin" (stock 0). `orden`: clave de ORDENES_INVENTARIO.
    `sin_costo` deja sólo los que no tienen costo anotado (sólo administrador).
    """
    if categoria not in (None, SIN_CATEGORIA):
        _exigir_mismo_almacen(almacen, categoria)
    if stock == "bajo":
        productos = productos_con_stock_bajo(almacen)
    else:
        productos = Producto.objects.del_almacen(almacen)
        if stock == "sin":
            productos = productos.filter(stock_actual=0)

    for palabra in (texto or "").split():
        productos = productos.filter(
            Q(nombre__icontains=palabra)
            | Q(codigo_barras__icontains=palabra)
            | Q(descripcion__icontains=palabra)
        )
    if categoria == SIN_CATEGORIA:
        productos = productos.filter(id_categoria__isnull=True)
    elif categoria is not None:
        productos = productos.filter(id_categoria=categoria)

    if sin_costo:
        productos = productos.filter(costo__isnull=True)

    campos = ORDENES_INVENTARIO.get(orden, ORDENES_INVENTARIO["nombre"])
    return productos.select_related("id_categoria").order_by(*campos)
