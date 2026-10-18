"""
Reporte mensual (CU-04) y alertas del panel (CU-05 y cierre de mes).

El reporte se calcula al vuelo en PostgreSQL: agrupaciones y funciones de ventana
(RANK, LAG, SUM(...) OVER ()), sin tablas precalculadas. A Python sólo llegan las
filas ya agregadas (a lo más diez productos, siete días, las franjas y unos meses).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from django.db import IntegrityError, transaction
from django.db.models import (
    Aggregate,
    Case,
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    Func,
    IntegerField,
    Min,
    OuterRef,
    Q,
    Subquery,
    Sum,
    When,
    Window,
)
from django.db.models.functions import (
    Abs,
    Coalesce,
    ExtractIsoWeekDay,
    Lag,
    Lead,
    Rank,
    TruncDate,
    TruncMonth,
    TruncTime,
)
from django.utils import timezone

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN, FranjaHoraria, condicion_franja
from apps.inventario.models import MotivoAjuste, MovimientoStock, TipoMovimiento
from apps.inventario.servicios import productos_con_stock_bajo
from apps.ventas.models import DetalleVenta, EstadoVenta, Venta

from .models import AccesoReporte, Alerta, TipoAlerta

TOPE_MAS_VENDIDOS = 10
MESES_EN_COMPARACION = 6  # el mes consultado y los cinco anteriores

NOMBRES_MES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
NOMBRES_DIA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def hora_local(campo):
    """`(campo AT TIME ZONE 'America/Santiago')::time`: hora de reloj del almacén."""
    return TruncTime(campo, tzinfo=ZONA_HORARIA_ALMACEN)


def anotar_franja(ventas, almacen):
    """
    Agrega `franja` (nombre) y `franja_orden` a un queryset de ventas, calculados en
    PostgreSQL. La comparación se hace en hora local, nunca en UTC.
    """
    ventas = ventas.annotate(hora_local=hora_local("fecha_hora"))
    franjas = FranjaHoraria.objects.del_almacen(almacen).filter(
        condicion_franja(OuterRef("hora_local"))
    )
    return ventas.annotate(
        franja=Subquery(franjas.values("nombre")[:1]),
        franja_orden=Subquery(franjas.values("orden")[:1]),
    )


def ajustes_de_exactitud(almacen):
    """
    Ajustes que cuentan para el indicador «exactitud de inventario» (§7): todos los
    movimientos tipo ajuste EXCEPTO los de «Alta rápida en caja», porque un producto
    que nace en el mesón no es una diferencia de inventario.
    """
    return (
        MovimientoStock.objects.del_almacen(almacen)
        .filter(tipo=TipoMovimiento.AJUSTE)
        .exclude(motivo=MotivoAjuste.ALTA_RAPIDA)
    )


class SumaVentana(Func):
    """
    `SUM(expr) OVER (...)` sobre un agregado, p. ej. SUM(COUNT(id_venta)) OVER ().
    El Sum de Django no acepta un agregado dentro; como función de ventana es válido.
    """

    function = "SUM"
    window_compatible = True


# --- Meses ---------------------------------------------------------------------------


def hoy_local():
    return timezone.localdate(timezone=ZONA_HORARIA_ALMACEN)


def primer_dia(fecha):
    return fecha.replace(day=1)


def mes_siguiente(mes):
    return date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)


def mes_anterior(mes):
    return (mes - timedelta(days=1)).replace(day=1)


def nombre_mes(mes):
    """date(2026, 9, 1) -> «septiembre 2026»."""
    return f"{NOMBRES_MES[mes.month - 1]} {mes.year}"


def inicio_del_dia(fecha):
    """Medianoche local del día, como datetime con zona (comparable con TIMESTAMPTZ)."""
    return datetime.combine(fecha, datetime.min.time(), tzinfo=ZONA_HORARIA_ALMACEN)


def leer_mes(texto):
    """«2026-09» -> date(2026, 9, 1). None si el texto no es un mes válido."""
    try:
        return date.fromisoformat(f"{texto}-01")
    except (TypeError, ValueError):
        return None


def inicio_de_registros(almacen):
    """
    Primer día con datos del almacén: el alta o la primera venta, lo que ocurra antes.
    Un mes que empezó antes de este día no está completo y no sirve como base.
    """
    alta = timezone.localtime(almacen.fecha_alta, ZONA_HORARIA_ALMACEN).date()
    primera = Venta.objects.del_almacen(almacen).aggregate(primera=Min("fecha_hora"))[
        "primera"
    ]
    if primera is None:
        return alta
    return min(alta, timezone.localtime(primera, ZONA_HORARIA_ALMACEN).date())


def meses_disponibles(almacen, hoy=None):
    """Meses que se pueden consultar, del más reciente al más antiguo."""
    hoy = hoy or hoy_local()
    mes, ultimo = primer_dia(inicio_de_registros(almacen)), primer_dia(hoy)
    meses = []
    while mes <= ultimo:
        meses.append(mes)
        mes = mes_siguiente(mes)
    return meses[::-1]


def _porcentaje(parte, total):
    if not total:
        return Decimal("0")
    return (Decimal(parte) * 100 / Decimal(total)).quantize(Decimal("0.1"), ROUND_HALF_UP)


# --- Consultas -----------------------------------------------------------------------


def _ventas_vigentes(almacen, desde, hasta):
    """Ventas vigentes con fecha_hora en [desde, hasta) (hora local). Usa ix_venta_fecha."""
    return Venta.objects.del_almacen(almacen).filter(
        estado=EstadoVenta.VIGENTE,
        fecha_hora__gte=inicio_del_dia(desde),
        fecha_hora__lt=inicio_del_dia(hasta),
    )


def mas_vendidos(almacen, mes):
    """
    Productos por unidades vendidas con RANK() OVER: los empates comparten lugar y
    el corte en TOPE_MAS_VENDIDOS no deja fuera a un producto empatado en el último.
    """
    filas = (
        DetalleVenta.objects.del_almacen(almacen)
        .filter(
            id_venta__estado=EstadoVenta.VIGENTE,
            id_venta__fecha_hora__gte=inicio_del_dia(mes),
            id_venta__fecha_hora__lt=inicio_del_dia(mes_siguiente(mes)),
        )
        .values("id_producto", "id_producto__nombre", "id_producto__codigo_barras")
        .annotate(
            unidades=Sum("cantidad"),
            monto=Sum("subtotal"),
            lugar=Window(Rank(), order_by=Sum("cantidad").desc()),
            unidades_mes=Window(SumaVentana(Sum("cantidad"))),
        )
        .order_by("lugar", "id_producto__nombre")
    )
    # Filtrar por una ventana envuelve la consulta: el total del mes se calcula antes.
    filas = filas.filter(lugar__lte=TOPE_MAS_VENDIDOS)
    return [
        {
            "lugar": fila["lugar"],
            "id_producto": fila["id_producto"],
            "nombre": fila["id_producto__nombre"],
            "codigo_barras": fila["id_producto__codigo_barras"],
            "unidades": fila["unidades"],
            "monto": fila["monto"],
            "participacion": _porcentaje(fila["unidades"], fila["unidades_mes"]),
        }
        for fila in filas
    ]


def _dias_por_semana(desde, hasta):
    """Cuántos lunes, martes... hay en [desde, hasta): un mes tiene 4 o 5 de cada uno."""
    cuenta = [0] * 7
    dia = desde
    while dia < hasta:
        cuenta[dia.weekday()] += 1
        dia += timedelta(days=1)
    return cuenta


def ventas_por_dia_semana(almacen, desde, hasta):
    """
    Ventas por día de la semana (hora local) en [desde, hasta). El promedio divide
    por cuántas veces aparece ese día en el período, para no favorecer al que trae
    cinco ocurrencias en el mes.
    """
    agregadas = {
        fila["dia"]: fila
        for fila in _ventas_vigentes(almacen, desde, hasta)
        .annotate(dia=ExtractIsoWeekDay("fecha_hora", tzinfo=ZONA_HORARIA_ALMACEN))
        .values("dia")
        .annotate(
            cantidad=Count("pk"),
            monto=Sum("total"),
            monto_periodo=Window(SumaVentana(Sum("total"))),
        )
        .order_by("dia")
    }
    ocurrencias = _dias_por_semana(desde, hasta)
    filas = []
    for indice, nombre in enumerate(NOMBRES_DIA):
        fila = agregadas.get(indice + 1, {})
        monto = fila.get("monto") or Decimal("0")
        dias = ocurrencias[indice]
        filas.append(
            {
                "dia": nombre,
                "cantidad": fila.get("cantidad", 0),
                "monto": monto,
                "dias": dias,
                "promedio_diario": (monto / dias).quantize(Decimal("1")) if dias else None,
                "participacion": _porcentaje(monto, fila.get("monto_periodo")),
            }
        )
    _marcar_mayor(filas, "promedio_diario")
    return filas


def ventas_por_franja(almacen, desde, hasta):
    """Ventas por franja horaria del almacén (hora local, franjas [inicio, fin))."""
    agregadas = {
        fila["franja_orden"]: fila
        for fila in anotar_franja(_ventas_vigentes(almacen, desde, hasta), almacen)
        .values("franja_orden")
        .annotate(
            cantidad=Count("pk"),
            monto=Sum("total"),
            cantidad_periodo=Window(SumaVentana(Count("pk"))),
        )
        .order_by("franja_orden")
    }
    filas = []
    for franja in FranjaHoraria.objects.del_almacen(almacen).order_by("orden"):
        fila = agregadas.get(franja.orden, {})
        filas.append(
            {
                "franja": franja.nombre,
                "horario": franja.etiqueta,
                "cantidad": fila.get("cantidad", 0),
                "monto": fila.get("monto") or Decimal("0"),
                "participacion": _porcentaje(
                    fila.get("cantidad", 0), fila.get("cantidad_periodo")
                ),
            }
        )
    _marcar_mayor(filas, "cantidad")
    return filas


def _marcar_mayor(filas, campo):
    mayor = max((fila[campo] or 0 for fila in filas), default=0)
    for fila in filas:
        fila["es_mayor"] = bool(mayor) and fila[campo] == mayor


def _mes_completo(mes, inicio_registros, hoy):
    return inicio_registros <= mes and mes_siguiente(mes) <= hoy


def comparacion_mensual(almacen, mes, hoy, inicio_registros):
    """
    Totales del mes consultado y los anteriores, con LAG() OVER para la variación.
    La variación sólo se calcula entre meses consecutivos y completos: un mes en
    curso o que empezó antes de que el almacén usara el sistema no es comparable.
    """
    primero = mes
    for _ in range(MESES_EN_COMPARACION):  # uno más, para la variación del más antiguo
        primero = mes_anterior(primero)
    mes_local = TruncMonth("fecha_hora", tzinfo=ZONA_HORARIA_ALMACEN)
    filas = (
        _ventas_vigentes(almacen, primero, mes_siguiente(mes))
        .annotate(mes=mes_local)
        .values("mes")
        .annotate(cantidad=Count("pk"), monto=Sum("total"))
        # Referirse al alias: con Lag(Sum(...)) Django mete la ventana en el GROUP BY.
        .annotate(monto_previo=Window(Lag("monto"), order_by=F("mes").asc()))
        .order_by("mes")
    )
    por_mes, previo = {}, None
    for fila in filas:
        actual = fila["mes"].date() if isinstance(fila["mes"], datetime) else fila["mes"]
        # LAG toma la fila anterior, que es el mes anterior sólo si éste tuvo ventas.
        variacion = None
        if (
            previo == mes_anterior(actual)
            and _mes_completo(actual, inicio_registros, hoy)
            and _mes_completo(previo, inicio_registros, hoy)
        ):
            variacion = _porcentaje(fila["monto"] - fila["monto_previo"], fila["monto_previo"])
        por_mes[actual] = {
            "cantidad": fila["cantidad"],
            "monto": fila["monto"],
            "variacion": variacion,
        }
        previo = actual

    serie = []
    mostrado = mes
    for _ in range(MESES_EN_COMPARACION):
        datos = por_mes.get(mostrado)
        serie.append(
            {
                "mes": mostrado,
                "nombre": nombre_mes(mostrado),
                "cantidad": datos["cantidad"] if datos else 0,
                "monto": datos["monto"] if datos else Decimal("0"),
                "variacion": datos["variacion"] if datos else None,
                "completo": _mes_completo(mostrado, inicio_registros, hoy),
                "consultado": mostrado == mes,
            }
        )
        mostrado = mes_anterior(mostrado)
        if mostrado < primer_dia(inicio_registros):
            break
    return serie[::-1], _motivo_sin_comparacion(mes, hoy, inicio_registros, por_mes)


def _motivo_sin_comparacion(mes, hoy, inicio_registros, por_mes):
    """None si el mes se puede comparar con el anterior; si no, el motivo (CU-04 3a)."""
    base = mes_anterior(mes)
    if mes_siguiente(mes) > hoy:
        return (
            f"{nombre_mes(mes).capitalize()} todavía no termina: la comparación con "
            f"{nombre_mes(base)} se muestra cuando cierre el mes."
        )
    if inicio_registros > mes:
        return (
            f"El almacén empezó a registrar en TivoScanea el {inicio_registros:%d-%m-%Y}: "
            f"{nombre_mes(mes)} no está completo y no se compara."
        )
    if base not in por_mes:
        return f"No hay ventas registradas en {nombre_mes(base)} para comparar."
    if inicio_registros > base:
        return (
            f"El almacén empezó a registrar en TivoScanea el {inicio_registros:%d-%m-%Y}: "
            f"{nombre_mes(base)} no está completo y no sirve como base."
        )
    return None


# --- Reporte -------------------------------------------------------------------------


@dataclass
class ReporteMensual:
    mes: date
    nombre: str
    hay_ventas: bool
    # Período con datos dentro del mes: [desde, hasta). Más corto que el mes si está en
    # curso o si el almacén empezó a registrar después del día 1.
    desde: date
    hasta: date
    en_curso: bool
    cantidad_ventas: int = 0
    monto_total: Decimal = Decimal("0")
    mas_vendidos: list = field(default_factory=list)
    por_dia_semana: list = field(default_factory=list)
    por_franja: list = field(default_factory=list)
    comparacion: list = field(default_factory=list)
    motivo_sin_comparacion: str | None = None
    variacion: Decimal | None = None

    @property
    def ultimo_dia(self):
        return self.hasta - timedelta(days=1)

    @property
    def mes_parcial(self):
        return self.desde != self.mes or self.hasta != mes_siguiente(self.mes)


def reporte_mensual(almacen, mes, hoy=None):
    """Arma el reporte de `mes` (primer día del mes). No registra el acceso."""
    hoy = hoy or hoy_local()
    mes = primer_dia(mes)
    if mes > primer_dia(hoy):
        raise ReglaDeNegocioError(f"{nombre_mes(mes).capitalize()} todavía no empieza.")
    inicio_registros = inicio_de_registros(almacen)
    desde = max(mes, inicio_registros)
    hasta = min(mes_siguiente(mes), hoy + timedelta(days=1))
    reporte = ReporteMensual(
        mes=mes,
        nombre=nombre_mes(mes),
        hay_ventas=False,
        desde=desde,
        hasta=max(desde, hasta),
        en_curso=mes_siguiente(mes) > hoy,
    )
    totales = _ventas_vigentes(almacen, mes, mes_siguiente(mes)).aggregate(
        cantidad=Count("pk"), monto=Sum("total")
    )
    if not totales["cantidad"]:
        return reporte  # CU-04 2a: la interfaz informa que no hay datos.
    reporte.hay_ventas = True
    reporte.cantidad_ventas = totales["cantidad"]
    reporte.monto_total = totales["monto"]
    reporte.mas_vendidos = mas_vendidos(almacen, mes)
    reporte.por_dia_semana = ventas_por_dia_semana(almacen, reporte.desde, reporte.hasta)
    reporte.por_franja = ventas_por_franja(almacen, mes, mes_siguiente(mes))
    reporte.comparacion, reporte.motivo_sin_comparacion = comparacion_mensual(
        almacen, mes, hoy, inicio_registros
    )
    if reporte.motivo_sin_comparacion is None:
        reporte.variacion = reporte.comparacion[-1]["variacion"]
    return reporte


@transaction.atomic
def consultar_reporte_mensual(*, almacen, usuario, mes, hoy=None):
    """
    CU-04: arma el reporte y registra el acceso (indicador «uso de la reportería»).
    Abrir el reporte de un mes cerrado da por vista su alerta de cierre de mes.
    """
    if usuario.id_almacen_id != almacen.pk:
        raise ReglaDeNegocioError("Ese usuario no pertenece a este almacén.")
    reporte = reporte_mensual(almacen, mes, hoy)
    AccesoReporte.objects.del_almacen(almacen).create(
        id_usuario=usuario, mes_consultado=reporte.mes
    )
    alertas_pendientes(almacen).filter(
        tipo=TipoAlerta.CIERRE_MES, fecha_referencia=reporte.mes
    ).update(fecha_vista=timezone.now(), id_usuario_vista=usuario)
    return reporte


# --- Alertas (CU-05 y cierre de mes) -------------------------------------------------


def alertas_pendientes(almacen):
    return Alerta.objects.del_almacen(almacen).filter(fecha_vista__isnull=True)


def alertas_del_panel(almacen):
    """
    Lo que muestra el panel: la revisión de stock bajo más reciente sin ver (las
    anteriores quedan superadas por ella) y los cierres de mes sin ver.
    """
    pendientes = alertas_pendientes(almacen)
    stock = pendientes.filter(tipo=TipoAlerta.STOCK_BAJO).order_by("-fecha_referencia")[:1]
    cierres = pendientes.filter(tipo=TipoAlerta.CIERRE_MES).order_by("-fecha_referencia")
    return list(stock) + list(cierres)


def _crear_alerta(almacen, tipo, fecha_referencia, mensaje):
    """Crea la alerta si no existe. Devuelve (alerta, creada)."""
    existentes = Alerta.objects.del_almacen(almacen).filter(
        tipo=tipo, fecha_referencia=fecha_referencia
    )
    existente = existentes.first()
    if existente:
        return existente, False
    try:
        with transaction.atomic():
            alerta = Alerta.objects.del_almacen(almacen).create(
                tipo=tipo, fecha_referencia=fecha_referencia, mensaje=mensaje
            )
    except IntegrityError:  # otra ejecución del comando la creó entremedio
        return existentes.get(), False
    return alerta, True


def alertar_stock_bajo(almacen, hoy=None):
    """
    CU-05: si hay productos con stock en o bajo el mínimo, deja una alerta del día.
    3a: si no hay ninguno, no genera alerta y devuelve (None, False).
    """
    hoy = hoy or hoy_local()
    cantidad = productos_con_stock_bajo(almacen).count()
    if not cantidad:
        return None, False
    if cantidad == 1:
        mensaje = "Hay 1 producto con stock bajo el mínimo. Revisa si hay que reponer."
    else:
        mensaje = (
            f"Hay {cantidad} productos con stock bajo el mínimo. Revisa si hay que reponer."
        )
    return _crear_alerta(almacen, TipoAlerta.STOCK_BAJO, hoy, mensaje)


def avisar_cierre_mes(almacen, hoy=None):
    """
    Cierre de mes: avisa que el reporte del mes anterior está disponible. No calcula
    el reporte. Si el mes no tuvo ventas no hay nada que avisar.
    """
    hoy = hoy or hoy_local()
    mes = mes_anterior(primer_dia(hoy))
    if not _ventas_vigentes(almacen, mes, mes_siguiente(mes)).exists():
        return None, False
    mensaje = f"Ya está disponible el reporte de {nombre_mes(mes)}."
    return _crear_alerta(almacen, TipoAlerta.CIERRE_MES, mes, mensaje)


def marcar_alerta_vista(*, almacen, alerta, usuario):
    """
    Da por vista la alerta. Una de stock bajo se lleva también las revisiones
    anteriores sin ver, que el panel ya no mostraba.
    """
    if alerta.id_almacen_id != almacen.pk or usuario.id_almacen_id != almacen.pk:
        raise ReglaDeNegocioError("Esa alerta no es de este almacén.")
    pendientes = alertas_pendientes(almacen).filter(tipo=alerta.tipo)
    if alerta.tipo == TipoAlerta.STOCK_BAJO:
        pendientes = pendientes.filter(fecha_referencia__lte=alerta.fecha_referencia)
    else:
        pendientes = pendientes.filter(pk=alerta.pk)
    return pendientes.update(fecha_vista=timezone.now(), id_usuario_vista=usuario)


# --- Indicadores (§7) ----------------------------------------------------------------

# Sin línea base medida no se muestra un número (§2.3): se mide con el almacén piloto.
LINEA_BASE_PENDIENTE = "Por medir en el levantamiento"


class Mediana(Aggregate):
    """`PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY expr)`: la mediana, en PostgreSQL."""

    function = "PERCENTILE_CONT"
    template = "%(function)s(0.5) WITHIN GROUP (ORDER BY %(expressions)s)"


def tiempo_de_registro(almacen, desde, hasta):
    """
    Tiempo de registro de venta: fecha_hora (confirmación) − hora_inicio (apertura).
    Cuenta también las anuladas: el tiempo en el mesón ya ocurrió. Las ventas sin
    hora de inicio (descartada por inválida) no se miden y se informan aparte.
    """
    ventas = Venta.objects.del_almacen(almacen).filter(
        fecha_hora__gte=inicio_del_dia(desde), fecha_hora__lt=inicio_del_dia(hasta)
    )
    return ventas.aggregate(
        medidas=Count("pk", filter=Q(hora_inicio__isnull=False)),
        sin_medir=Count("pk", filter=Q(hora_inicio__isnull=True)),
        mediana=Mediana(
            ExpressionWrapper(
                F("fecha_hora") - F("hora_inicio"), output_field=DurationField()
            ),
            output_field=DurationField(),
        ),
    )


def quiebres_de_stock(almacen, desde, hasta):
    """
    Quiebres de stock: cada vez que la serie de movimiento_stock de un producto llega
    a 0, y cuánto tarda en volver a subir (el movimiento siguiente siempre es un alza,
    porque el stock nunca es negativo). El stock tras cada movimiento es la suma
    acumulada por producto (SUM(...) OVER); se calcula sobre toda la historia, así
    que el filtro por fecha se aplica después, en Python, sobre las pocas filas en 0.
    """
    delta = Case(
        When(tipo=TipoMovimiento.SALIDA, then=-F("cantidad")),
        default=F("cantidad"),
        output_field=IntegerField(),
    )
    por_producto = {
        "partition_by": F("id_producto"),
        "order_by": (F("fecha_hora").asc(), F("id_movimiento").asc()),
    }
    en_cero = (
        MovimientoStock.objects.del_almacen(almacen)
        .annotate(
            stock_tras=Window(Sum(delta), **por_producto),
            siguiente=Window(Lead("fecha_hora"), **por_producto),
        )
        .filter(stock_tras=0)
        .values("id_producto", "fecha_hora", "siguiente")
    )
    desde, hasta = inicio_del_dia(desde), inicio_del_dia(hasta)
    quiebres = [fila for fila in en_cero if desde <= fila["fecha_hora"] < hasta]
    esperas = [f["siguiente"] - f["fecha_hora"] for f in quiebres if f["siguiente"]]
    return {
        "quiebres": len(quiebres),
        "productos": len({fila["id_producto"] for fila in quiebres}),
        "sin_reponer": len(quiebres) - len(esperas),
        "mediana_reposicion": median(esperas) if esperas else None,
    }


def exactitud_de_inventario(almacen, desde, hasta):
    """Ajustes del período que cuentan para la exactitud (sin «Alta rápida en caja»)."""
    return (
        ajustes_de_exactitud(almacen)
        .filter(fecha_hora__gte=inicio_del_dia(desde), fecha_hora__lt=inicio_del_dia(hasta))
        .aggregate(
            ajustes=Count("pk"),
            unidades=Coalesce(Sum(Abs("cantidad")), 0),
            productos=Count("id_producto", distinct=True),
        )
    )


def uso_de_reporteria(almacen, desde, hasta):
    """Consultas del reporte mensual en el período (tabla acceso_reporte)."""
    return (
        AccesoReporte.objects.del_almacen(almacen)
        .filter(fecha_hora__gte=inicio_del_dia(desde), fecha_hora__lt=inicio_del_dia(hasta))
        .aggregate(
            consultas=Count("pk"),
            dias=Count(TruncDate("fecha_hora", tzinfo=ZONA_HORARIA_ALMACEN), distinct=True),
        )
    )


@dataclass
class Indicadores:
    mes: date
    nombre: str
    desde: date
    hasta: date
    en_curso: bool
    hay_movimientos: bool
    tiempo: dict
    quiebres: dict
    exactitud: dict
    uso: dict
    linea_base: str = LINEA_BASE_PENDIENTE

    @property
    def ultimo_dia(self):
        return self.hasta - timedelta(days=1)

    @property
    def mes_parcial(self):
        return self.desde != self.mes or self.hasta != mes_siguiente(self.mes)


def indicadores(almacen, mes, hoy=None):
    """
    Los cuatro indicadores de §7 en `mes`, calculados al vuelo. Ver los indicadores no
    cuenta como uso de la reportería (no registra acceso_reporte).
    """
    hoy = hoy or hoy_local()
    mes = primer_dia(mes)
    if mes > primer_dia(hoy):
        raise ReglaDeNegocioError(f"{nombre_mes(mes).capitalize()} todavía no empieza.")
    desde = max(mes, inicio_de_registros(almacen))
    hasta = max(desde, min(mes_siguiente(mes), hoy + timedelta(days=1)))
    return Indicadores(
        mes=mes,
        nombre=nombre_mes(mes),
        desde=desde,
        hasta=hasta,
        en_curso=mes_siguiente(mes) > hoy,
        hay_movimientos=MovimientoStock.objects.del_almacen(almacen)
        .filter(fecha_hora__gte=inicio_del_dia(desde), fecha_hora__lt=inicio_del_dia(hasta))
        .exists(),
        tiempo=tiempo_de_registro(almacen, desde, hasta),
        quiebres=quiebres_de_stock(almacen, desde, hasta),
        exactitud=exactitud_de_inventario(almacen, desde, hasta),
        uso=uso_de_reporteria(almacen, desde, hasta),
    )
