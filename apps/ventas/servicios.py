"""
Reglas de negocio de Ventas: registrar (CU-02) y anular (CU-03).

La venta completa ocurre en UNA transacción: detalle, ajustes por diferencia de
inventario, salidas de stock y total. Si cualquier paso falla, no queda nada.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN
from apps.inventario.models import MotivoAjuste, MovimientoStock, TipoMovimiento
from apps.inventario.servicios import aplicar_ajuste, bloquear_productos, registrar_movimiento

from .models import MOTIVO_ANULACION_LARGO_MINIMO, DetalleVenta, EstadoVenta, MedioPago, Venta

# Una hora de inicio más antigua que esto no es la apertura de esta venta (p. ej. una
# pestaña que quedó abierta desde ayer): se descarta en vez de ensuciar el indicador.
ANTIGUEDAD_MAXIMA_HORA_INICIO = timedelta(hours=12)


@dataclass(frozen=True)
class LineaVenta:
    id_producto: int
    cantidad: int
    # El producto se dio de alta en la caja durante esta venta (CU-02 2a).
    alta_rapida: bool = False


@dataclass(frozen=True)
class Diferencia:
    id_producto: int
    nombre: str
    stock: int
    cantidad: int

    @property
    def unidades(self):
        return self.cantidad - self.stock

    @property
    def mensaje(self):
        return (
            f"El sistema tiene {self.stock} unidad{'es' if self.stock != 1 else ''} de "
            f"«{self.nombre}» y estás vendiendo {self.cantidad}. Si continúas, se registra "
            f"una diferencia de inventario de {self.unidades} "
            f"unidad{'es' if self.unidades != 1 else ''}."
        )


class StockInsuficienteError(ReglaDeNegocioError):
    """CU-02 6a: hay que advertir y pedir confirmación explícita antes de vender."""

    def __init__(self, diferencias):
        self.diferencias = diferencias
        super().__init__(" ".join(d.mensaje for d in diferencias))


def _exigir_mismo_almacen(almacen, *registros):
    id_almacen = getattr(almacen, "pk", almacen)
    for registro in registros:
        if registro is not None and registro.id_almacen_id != id_almacen:
            raise ReglaDeNegocioError("Ese registro no pertenece a tu almacén.")


def _agrupar(lineas):
    """Suma las cantidades del mismo producto (escaneado varias veces)."""
    agrupadas = {}
    for linea in lineas:
        if not isinstance(linea.cantidad, int) or linea.cantidad <= 0:
            raise ReglaDeNegocioError("Todas las cantidades deben ser mayores que cero.")
        previa = agrupadas.get(linea.id_producto)
        if previa:
            linea = LineaVenta(
                linea.id_producto,
                previa.cantidad + linea.cantidad,
                previa.alta_rapida or linea.alta_rapida,
            )
        agrupadas[linea.id_producto] = linea
    return agrupadas


def _hora_inicio_valida(hora_inicio, ahora):
    if hora_inicio is None or hora_inicio > ahora:
        return None
    if ahora - hora_inicio > ANTIGUEDAD_MAXIMA_HORA_INICIO:
        return None
    return hora_inicio


def _es_alta_rapida(almacen, producto, linea):
    """
    La caja dice que el producto nació en esta venta; se verifica en vez de
    creerle: un producto recién creado no tiene ningún movimiento todavía.
    """
    return (
        linea.alta_rapida
        and not MovimientoStock.objects.del_almacen(almacen)
        .filter(id_producto=producto)
        .exists()
    )


def registrar_venta(
    *, almacen, usuario, lineas, medio_pago, hora_inicio=None, confirmar_diferencias=False
):
    """
    CU-02. Si a algún producto le falta stock y no se confirmó la diferencia, lanza
    StockInsuficienteError sin escribir nada. Con confirmación (o si el producto es
    de alta rápida), por cada faltante registra primero un ajuste por la diferencia
    y después la salida: el stock nunca queda negativo y la diferencia queda auditada.
    """
    _exigir_mismo_almacen(almacen, usuario)
    if medio_pago not in MedioPago.values:
        raise ReglaDeNegocioError("Elige un medio de pago.")
    agrupadas = _agrupar(lineas)
    if not agrupadas:
        raise ReglaDeNegocioError("La venta no tiene productos.")
    ahora = timezone.now()

    with transaction.atomic():
        productos = bloquear_productos(almacen, agrupadas.keys())
        if len(productos) != len(agrupadas):
            raise ReglaDeNegocioError(
                "Uno de los productos ya no existe. Vuelve a escanearlo."
            )

        motivos = {}
        sin_confirmar = []
        for pk in sorted(agrupadas):
            producto, linea = productos[pk], agrupadas[pk]
            if producto.stock_actual >= linea.cantidad:
                continue
            if _es_alta_rapida(almacen, producto, linea):
                motivos[pk] = MotivoAjuste.ALTA_RAPIDA
            else:
                motivos[pk] = MotivoAjuste.VENTA_SIN_STOCK
                sin_confirmar.append(
                    Diferencia(pk, producto.nombre, producto.stock_actual, linea.cantidad)
                )
        if sin_confirmar and not confirmar_diferencias:
            raise StockInsuficienteError(sin_confirmar)

        venta = Venta.objects.del_almacen(almacen).create(
            id_usuario=usuario,
            fecha_hora=ahora,
            hora_inicio=_hora_inicio_valida(hora_inicio, ahora),
            total=Decimal("0"),
            medio_pago=medio_pago,
        )
        total = Decimal("0")
        for pk in sorted(agrupadas):
            producto, cantidad = productos[pk], agrupadas[pk].cantidad
            if pk in motivos:
                aplicar_ajuste(
                    producto=producto,
                    diferencia=cantidad - producto.stock_actual,
                    motivo=motivos[pk],
                    usuario=usuario,
                    venta=venta,
                )
            producto.stock_actual -= cantidad
            producto.save(update_fields=["stock_actual"])
            registrar_movimiento(
                producto=producto,
                tipo=TipoMovimiento.SALIDA,
                cantidad=cantidad,
                usuario=usuario,
                venta=venta,
            )
            subtotal = producto.precio * cantidad
            _crear_detalle(venta, producto, cantidad, subtotal)
            total += subtotal

        venta.total = total
        venta.save(update_fields=["total"])
    return venta


def _crear_detalle(venta, producto, cantidad, subtotal):
    # detalle_venta.id_almacen es redundante con el de la venta: deben coincidir.
    _exigir_mismo_almacen(venta.id_almacen_id, producto)
    return DetalleVenta.objects.del_almacen(venta.id_almacen_id).create(
        id_venta=venta,
        id_producto=producto,
        cantidad=cantidad,
        precio_unitario=producto.precio,
        subtotal=subtotal,
    )


def limite_anulacion(venta):
    """
    Último instante (exclusivo) en que la venta se puede anular: el minuto
    `hora_limite_anulacion` del día de la venta, en hora local del almacén, incluido
    completo. Con el valor por defecto 23:59, se puede anular hasta las 23:59:59.

    Limitación declarada: un almacén que cierra después de medianoche no queda bien
    modelado; una venta de la 01:30 pertenece al día calendario en que ocurrió.
    """
    dia_local = timezone.localtime(venta.fecha_hora, ZONA_HORARIA_ALMACEN).date()
    hora_limite = venta.id_almacen.hora_limite_anulacion
    return datetime.combine(dia_local, hora_limite, tzinfo=ZONA_HORARIA_ALMACEN) + timedelta(
        minutes=1
    )


def anulacion_en_plazo(venta, momento=None):
    momento = momento or timezone.now()
    return momento < limite_anulacion(venta)


def anular_venta(*, almacen, venta, usuario, motivo, momento=None):
    """
    CU-03. Pueden anular el administrador y el vendedor (decidido 2026-10-14): el
    control es el registro de quién, cuándo y por qué. La venta no se borra: pasa a
    `anulada` y cada producto recupera su stock con una entrada ligada a la venta.
    """
    _exigir_mismo_almacen(almacen, venta, usuario)
    motivo = (motivo or "").strip()
    if len(motivo) < MOTIVO_ANULACION_LARGO_MINIMO:
        raise ReglaDeNegocioError(
            "Escribe el motivo de la anulación "
            f"(al menos {MOTIVO_ANULACION_LARGO_MINIMO} letras)."
        )
    momento = momento or timezone.now()

    with transaction.atomic():
        venta = (
            Venta.objects.del_almacen(almacen)
            .select_for_update()
            .select_related("id_almacen")
            .get(pk=venta.pk)
        )
        if venta.estado == EstadoVenta.ANULADA:
            raise ReglaDeNegocioError(f"La venta N° {venta.id_venta} ya estaba anulada.")
        if not anulacion_en_plazo(venta, momento):
            limite = timezone.localtime(limite_anulacion(venta), ZONA_HORARIA_ALMACEN)
            ultimo_minuto = limite - timedelta(minutes=1)
            raise ReglaDeNegocioError(
                f"Ya no se puede anular la venta N° {venta.id_venta}: el plazo terminó a las "
                f"{ultimo_minuto:%H:%M} del {ultimo_minuto:%d/%m/%Y}."
            )

        detalles = list(DetalleVenta.objects.del_almacen(almacen).filter(id_venta=venta))
        productos = bloquear_productos(almacen, [d.id_producto_id for d in detalles])
        for detalle in sorted(detalles, key=lambda d: d.id_producto_id):
            producto = productos[detalle.id_producto_id]
            producto.stock_actual += detalle.cantidad
            producto.save(update_fields=["stock_actual"])
            registrar_movimiento(
                producto=producto,
                tipo=TipoMovimiento.ENTRADA,
                cantidad=detalle.cantidad,
                usuario=usuario,
                venta=venta,
            )

        venta.estado = EstadoVenta.ANULADA
        venta.id_usuario_anulacion = usuario
        venta.fecha_anulacion = momento
        venta.motivo_anulacion = motivo
        venta.save(
            update_fields=[
                "estado",
                "id_usuario_anulacion",
                "fecha_anulacion",
                "motivo_anulacion",
            ]
        )
    return venta
