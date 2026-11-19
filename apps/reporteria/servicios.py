"""
Reporte (CU-04) por semana, mes o año, y alertas del panel (CU-05 y cierre de mes).

El reporte se calcula al vuelo en PostgreSQL: agrupaciones y funciones de ventana
(RANK, LAG, SUM(...) OVER ()), sin tablas precalculadas. A Python sólo llegan las
filas ya agregadas (a lo más veinte productos por lista, siete días, las franjas, los
días o meses del período y unos períodos anteriores).
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
    DecimalField,
    DurationField,
    Exists,
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
    TruncWeek,
    TruncYear,
)
from django.utils import timezone

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN, FranjaHoraria, condicion_franja
from apps.inventario.models import MotivoAjuste, MovimientoStock, Producto, TipoMovimiento
from apps.inventario.servicios import productos_con_stock_bajo
from apps.ventas.models import DetalleVenta, EstadoVenta, Venta

from .models import AccesoReporte, Alerta, TipoAlerta, TipoPeriodo
from .periodos import (  # noqa: F401 (mes_siguiente, NOMBRES_*: los importan otros módulos)
    EN_COMPARACION,
    NOMBRES_DIA,
    NOMBRES_MES,
    Periodo,
    leer_periodo,
    mes_anterior,
    mes_siguiente,
    nombre_mes,
)

TOPE_MAS_VENDIDOS = 10
TOPE_SIN_VENTAS = 20  # filas de la tabla; el total y el valor cuentan todos
MESES_EN_COMPARACION = EN_COMPARACION[TipoPeriodo.MES]


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


def periodos_disponibles(almacen, tipo, hoy=None):
    """Períodos que se pueden consultar, del más reciente al más antiguo."""
    hoy = hoy or hoy_local()
    periodo = Periodo.que_contiene(tipo, inicio_de_registros(almacen))
    ultimo = Periodo.que_contiene(tipo, hoy)
    periodos = []
    while periodo.inicio <= ultimo.inicio:
        periodos.append(periodo)
        periodo = periodo.siguiente
    return periodos[::-1]


def meses_disponibles(almacen, hoy=None):
    return [p.inicio for p in periodos_disponibles(almacen, TipoPeriodo.MES, hoy)]


def periodo_por_omision(almacen, tipo, hoy=None):
    """
    El último período cerrado (el mes anterior es el que avisa el cierre de mes); si el
    almacén todavía no tenía registros en él, el período en curso.
    """
    hoy = hoy or hoy_local()
    actual = Periodo.que_contiene(tipo, hoy)
    if tipo == TipoPeriodo.MES:
        return actual.anterior  # se mantiene: el aviso de cierre lleva a este mes
    primero = Periodo.que_contiene(tipo, inicio_de_registros(almacen))
    return actual.anterior if actual.anterior.inicio >= primero.inicio else actual


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


def _detalles_vigentes(almacen, desde, hasta):
    """Líneas de ventas vigentes con fecha_hora en [desde, hasta) (hora local)."""
    return DetalleVenta.objects.del_almacen(almacen).filter(
        id_venta__estado=EstadoVenta.VIGENTE,
        id_venta__fecha_hora__gte=inicio_del_dia(desde),
        id_venta__fecha_hora__lt=inicio_del_dia(hasta),
    )


def _ranking(almacen, desde, hasta):
    """
    Unidades por producto con dos RANK() OVER: de más a menos vendido (`lugar`) y al
    revés (`lugar_desde_abajo`). Los empates comparten lugar.
    """
    return (
        _detalles_vigentes(almacen, desde, hasta)
        .values(
            "id_producto",
            "id_producto__nombre",
            "id_producto__codigo_barras",
            "id_producto__stock_actual",
        )
        .annotate(
            unidades=Sum("cantidad"),
            monto=Sum("subtotal"),
            lugar=Window(Rank(), order_by=Sum("cantidad").desc()),
            lugar_desde_abajo=Window(Rank(), order_by=Sum("cantidad").asc()),
            unidades_periodo=Window(SumaVentana(Sum("cantidad"))),
        )
    )


def _fila_de_ranking(fila):
    return {
        "lugar": fila["lugar"],
        "id_producto": fila["id_producto"],
        "nombre": fila["id_producto__nombre"],
        "codigo_barras": fila["id_producto__codigo_barras"],
        "stock_actual": fila["id_producto__stock_actual"],
        "unidades": fila["unidades"],
        "monto": fila["monto"],
        "participacion": _porcentaje(fila["unidades"], fila["unidades_periodo"]),
    }


def mas_vendidos(almacen, desde, hasta):
    """
    Los más vendidos en [desde, hasta). El corte en TOPE_MAS_VENDIDOS no deja fuera a un
    producto empatado en el último lugar.
    """
    # Filtrar por una ventana envuelve la consulta: el total del período va antes.
    filas = (
        _ranking(almacen, desde, hasta)
        .filter(lugar__lte=TOPE_MAS_VENDIDOS)
        .order_by("lugar", "id_producto__nombre")
    )
    return [_fila_de_ranking(fila) for fila in filas]


def menos_vendidos(almacen, desde, hasta):
    """
    Los que se vendieron, pero poco: los últimos TOPE_MAS_VENDIDOS lugares, sin repetir
    los que ya están entre los más vendidos. Con diez productos vendidos o menos queda
    vacía (todos están arriba). Los que no se vendieron nada van en `sin_ventas`.
    """
    filas = (
        _ranking(almacen, desde, hasta)
        .filter(lugar_desde_abajo__lte=TOPE_MAS_VENDIDOS, lugar__gt=TOPE_MAS_VENDIDOS)
        .order_by("lugar_desde_abajo", "id_producto__nombre")
    )
    return [_fila_de_ranking(fila) for fila in filas]


def sin_ventas(almacen, desde, hasta):
    """
    Productos registrados antes del fin del período que no tuvieron ninguna venta
    vigente en él: stock que no se mueve. Se ordenan por stock de hoy (el que más
    plata tiene parada primero). `nuevo` marca a los registrados durante el período,
    que no estuvieron disponibles todos los días. El valor es a precio de venta: el
    sistema no guarda el costo.
    """
    vendidos = _detalles_vigentes(almacen, desde, hasta).filter(id_producto=OuterRef("pk"))
    productos = (
        Producto.objects.del_almacen(almacen)
        .filter(fecha_creacion__lt=inicio_del_dia(hasta))
        .exclude(Exists(vendidos))
    )
    valor = ExpressionWrapper(
        F("stock_actual") * F("precio"),
        output_field=DecimalField(max_digits=20, decimal_places=0),
    )
    resumen = productos.aggregate(
        cantidad=Count("pk"),
        unidades=Coalesce(Sum("stock_actual"), 0),
        valor=Coalesce(Sum(valor), Decimal("0")),
    )
    inicio = inicio_del_dia(desde)
    filas = productos.order_by("-stock_actual", "nombre").values(
        "id_producto", "nombre", "codigo_barras", "stock_actual", "precio", "fecha_creacion"
    )[:TOPE_SIN_VENTAS]
    return {
        **resumen,
        "productos": [
            {
                **fila,
                "nuevo": fila["fecha_creacion"] >= inicio,
                "alta": timezone.localtime(
                    fila["fecha_creacion"], ZONA_HORARIA_ALMACEN
                ).date(),
            }
            for fila in filas
        ],
    }


def ventas_por_categoria(almacen, desde, hasta):
    """Lo vendido por categoría, de mayor a menor monto. Sin categoría va aparte."""
    filas = (
        _detalles_vigentes(almacen, desde, hasta)
        .values(categoria=F("id_producto__id_categoria__nombre"))
        .annotate(
            unidades=Sum("cantidad"),
            monto=Sum("subtotal"),
            monto_periodo=Window(SumaVentana(Sum("subtotal"))),
        )
        .order_by("-monto", "categoria")
    )
    return [
        {
            "categoria": fila["categoria"] or "Sin categoría",
            "sin_categoria": fila["categoria"] is None,
            "unidades": fila["unidades"],
            "monto": fila["monto"],
            "participacion": _porcentaje(fila["monto"], fila["monto_periodo"]),
        }
        for fila in filas
    ]


def ventas_por_dia(almacen, desde, hasta):
    """
    Lo vendido en cada día de [desde, hasta) (hora local). Trae todos los días del
    período, también los sin ventas; los días fuera del período no se inventan en cero.
    """
    agregadas = {
        fila["dia"]: fila
        for fila in _ventas_vigentes(almacen, desde, hasta)
        .annotate(dia=TruncDate("fecha_hora", tzinfo=ZONA_HORARIA_ALMACEN))
        .values("dia")
        .annotate(cantidad=Count("pk"), monto=Sum("total"))
        .order_by("dia")
    }
    filas = []
    fecha = desde
    while fecha < hasta:
        fila = agregadas.get(fecha, {})
        filas.append(
            {
                "fecha": fecha,
                "etiqueta": f"{NOMBRES_DIA[fecha.weekday()].lower()} {fecha.day}",
                "cantidad": fila.get("cantidad", 0),
                "monto": fila.get("monto") or Decimal("0"),
            }
        )
        fecha += timedelta(days=1)
    _marcar_mayor(filas, "monto")
    return filas


def ventas_por_mes(almacen, desde, hasta):
    """
    Lo vendido en cada mes de [desde, hasta), para el reporte del año. Igual que por día:
    trae los meses del período sin ventas y no inventa los que no han llegado.
    """
    agregadas = {
        _como_fecha(fila["mes"]): fila
        for fila in _ventas_vigentes(almacen, desde, hasta)
        .annotate(mes=TruncMonth("fecha_hora", tzinfo=ZONA_HORARIA_ALMACEN))
        .values("mes")
        .annotate(cantidad=Count("pk"), monto=Sum("total"))
        .order_by("mes")
    }
    filas = []
    mes = primer_dia(desde)
    while mes < hasta:
        fila = agregadas.get(mes, {})
        filas.append(
            {
                "fecha": mes,
                "etiqueta": nombre_mes(mes),
                "rotulo": NOMBRES_MES[mes.month - 1][:3],
                "cantidad": fila.get("cantidad", 0),
                "monto": fila.get("monto") or Decimal("0"),
            }
        )
        mes = mes_siguiente(mes)
    _marcar_mayor(filas, "monto")
    return filas


def _como_fecha(valor):
    """TruncMonth/TruncWeek devuelven datetime con zona; la serie se arma con date."""
    return valor.date() if isinstance(valor, datetime) else valor


def _escala_del_eje(maximo):
    """Paso y tope redondos del eje, en hasta cuatro divisiones: 45.000 -> 20.000 y 60.000."""
    magnitud = 10 ** (len(str(maximo)) - 1)
    for base in (magnitud // 10 or 1, magnitud, magnitud * 10):
        for factor in (1, 2, 5):
            paso = base * factor
            divisiones = -(-maximo // paso)  # división hacia arriba
            if divisiones <= 4:
                return paso, paso * divisiones
    raise AssertionError("magnitud * 10 siempre alcanza")  # pragma: no cover


def armar_grafico(filas):
    """Alturas (% del tope), marcas del eje y rótulos del gráfico de barras del reporte."""
    maximo = int(max((fila["monto"] for fila in filas), default=0)) or 1
    paso, tope = _escala_del_eje(maximo)
    barras = []
    for indice, fila in enumerate(filas):
        if "rotulo" in fila:  # semana (cada día) y año (cada mes): todas rotuladas
            rotulo = fila["rotulo"]
        else:
            dia = fila["fecha"].day
            # Cada cinco días, más el primero si no queda pegado al rótulo siguiente.
            rotulo = dia if dia % 5 == 0 or (indice == 0 and dia % 5 != 4) else ""
        barras.append({**fila, "altura": _porcentaje(fila["monto"], tope), "rotulo": rotulo})
    return {
        "barras": barras,
        "marcas": [
            {"monto": monto, "altura": _porcentaje(monto, tope)}
            for monto in range(0, tope + 1, paso)
        ],
        "dias_mayores": ", ".join(f["etiqueta"] for f in filas if f["es_mayor"]),
        "monto_mayor": max((fila["monto"] for fila in filas), default=Decimal("0")),
    }


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


def _completo(periodo, inicio_registros, hoy):
    """Un período sirve para comparar si ya terminó y el almacén lo registró entero."""
    return inicio_registros <= periodo.inicio and periodo.fin <= hoy


TRUNCAR = {
    TipoPeriodo.SEMANA: TruncWeek,
    TipoPeriodo.MES: TruncMonth,
    TipoPeriodo.ANIO: TruncYear,
}


def comparacion(almacen, periodo, hoy, inicio_registros):
    """
    Totales del período consultado y los anteriores (EN_COMPARACION según el tipo), con
    LAG() OVER para la variación. La variación sólo se calcula entre períodos seguidos y
    completos: uno en curso o que empezó antes de que el almacén usara el sistema no es
    comparable (CU-04 3a).
    """
    cuantos = EN_COMPARACION[periodo.tipo]
    primero = periodo
    for _ in range(cuantos):  # uno más, para la variación del más antiguo
        primero = primero.anterior
    filas = (
        _ventas_vigentes(almacen, primero.inicio, periodo.fin)
        .annotate(inicio=TRUNCAR[periodo.tipo]("fecha_hora", tzinfo=ZONA_HORARIA_ALMACEN))
        .values("inicio")
        .annotate(cantidad=Count("pk"), monto=Sum("total"))
        # Referirse al alias: con Lag(Sum(...)) Django mete la ventana en el GROUP BY.
        .annotate(monto_previo=Window(Lag("monto"), order_by=F("inicio").asc()))
        .order_by("inicio")
    )
    por_inicio, previo = {}, None
    for fila in filas:
        actual = Periodo(periodo.tipo, _como_fecha(fila["inicio"]))
        # LAG toma la fila anterior, que es el período anterior sólo si éste tuvo ventas.
        variacion = None
        if (
            previo == actual.anterior
            and _completo(actual, inicio_registros, hoy)
            and _completo(previo, inicio_registros, hoy)
        ):
            variacion = _porcentaje(fila["monto"] - fila["monto_previo"], fila["monto_previo"])
        por_inicio[actual.inicio] = {
            "cantidad": fila["cantidad"],
            "monto": fila["monto"],
            "variacion": variacion,
        }
        previo = actual

    serie = []
    mostrado = periodo
    primero_registrado = Periodo.que_contiene(periodo.tipo, inicio_registros)
    for _ in range(cuantos):
        datos = por_inicio.get(mostrado.inicio)
        serie.append(
            {
                "inicio": mostrado.inicio,
                "nombre": mostrado.etiqueta,
                "cantidad": datos["cantidad"] if datos else 0,
                "monto": datos["monto"] if datos else Decimal("0"),
                "variacion": datos["variacion"] if datos else None,
                "completo": _completo(mostrado, inicio_registros, hoy),
                "consultado": mostrado == periodo,
            }
        )
        mostrado = mostrado.anterior
        if mostrado.inicio < primero_registrado.inicio:
            break
    return serie[::-1], _motivo_sin_comparacion(periodo, hoy, inicio_registros, por_inicio)


def comparacion_mensual(almacen, mes, hoy, inicio_registros):
    return comparacion(almacen, Periodo(TipoPeriodo.MES, mes), hoy, inicio_registros)


def _motivo_sin_comparacion(periodo, hoy, inicio_registros, por_inicio):
    """None si el período se puede comparar con el anterior; si no, el motivo (CU-04 3a)."""
    base = periodo.anterior
    if periodo.fin > hoy:
        return (
            f"{periodo.nombre.capitalize()} todavía no termina: la comparación con "
            f"{base.nombre} se muestra cuando {periodo.cuando_termina}."
        )
    if inicio_registros > periodo.inicio:
        return (
            f"El almacén empezó a registrar en TivoScanea el {inicio_registros:%d-%m-%Y}: "
            f"{periodo.nombre} no está {periodo.completo_palabra} y no se compara."
        )
    if base.inicio not in por_inicio:
        return f"No hay ventas registradas en {base.nombre} para comparar."
    if inicio_registros > base.inicio:
        return (
            f"El almacén empezó a registrar en TivoScanea el {inicio_registros:%d-%m-%Y}: "
            f"{base.nombre} no está {base.completo_palabra} y no sirve como base."
        )
    return None


# --- Reporte -------------------------------------------------------------------------


@dataclass
class Reporte:
    periodo: Periodo
    nombre: str
    hay_ventas: bool
    # Tramo con datos dentro del período: [desde, hasta). Más corto que el período si
    # está en curso o si el almacén empezó a registrar después de su primer día.
    desde: date
    hasta: date
    en_curso: bool
    cantidad_ventas: int = 0
    monto_total: Decimal = Decimal("0")
    unidades: int = 0
    mas_vendidos: list = field(default_factory=list)
    menos_vendidos: list = field(default_factory=list)
    sin_ventas: dict = field(default_factory=dict)
    por_categoria: list = field(default_factory=list)
    # Barras del gráfico: por día (semana y mes) o por mes (año).
    por_dia: list = field(default_factory=list)
    por_dia_semana: list = field(default_factory=list)
    por_franja: list = field(default_factory=list)
    comparacion: list = field(default_factory=list)
    motivo_sin_comparacion: str | None = None
    variacion: Decimal | None = None

    @property
    def tipo(self):
        return self.periodo.tipo

    @property
    def mes(self):
        """Primer día del período (en el reporte mensual, el mes)."""
        return self.periodo.inicio

    @property
    def ultimo_dia(self):
        return self.hasta - timedelta(days=1)

    @property
    def mes_parcial(self):
        return self.desde != self.periodo.inicio or self.hasta != self.periodo.fin

    @property
    def ticket_promedio(self):
        if not self.cantidad_ventas:
            return None
        return (self.monto_total / self.cantidad_ventas).quantize(Decimal("1"), ROUND_HALF_UP)

    @property
    def productos_vendidos(self):
        """Productos distintos vendidos (el ranking los trae todos con su lugar)."""
        return len(self.mas_vendidos) + len(self.menos_vendidos)

    @property
    def por_mes(self):
        return self.tipo == TipoPeriodo.ANIO

    @property
    def grafico(self):
        return armar_grafico(self.por_dia)

    grafico_diario = grafico


ReporteMensual = Reporte


def _ventas_por_dia_de_la_semana(almacen, desde, hasta):
    """Por día con el nombre corto como rótulo de cada barra: «lun 9»."""
    filas = ventas_por_dia(almacen, desde, hasta)
    for fila in filas:
        fila["rotulo"] = (
            f"{NOMBRES_DIA[fila['fecha'].weekday()][:3].lower()} {fila['fecha'].day}"
        )
    return filas


def reporte(almacen, periodo, hoy=None):
    """Arma el reporte del período (semana, mes o año). No registra el acceso."""
    hoy = hoy or hoy_local()
    if periodo.inicio > hoy:
        raise ReglaDeNegocioError(f"{periodo.nombre.capitalize()} todavía no empieza.")
    inicio_registros = inicio_de_registros(almacen)
    desde = max(periodo.inicio, inicio_registros)
    hasta = min(periodo.fin, hoy + timedelta(days=1))
    resultado = Reporte(
        periodo=periodo,
        nombre=periodo.nombre,
        hay_ventas=False,
        desde=desde,
        hasta=max(desde, hasta),
        en_curso=periodo.fin > hoy,
    )
    inicio, fin = periodo.inicio, periodo.fin
    totales = _ventas_vigentes(almacen, inicio, fin).aggregate(
        cantidad=Count("pk"), monto=Sum("total")
    )
    if not totales["cantidad"]:
        return resultado  # CU-04 2a: la interfaz informa que no hay datos.
    resultado.hay_ventas = True
    resultado.cantidad_ventas = totales["cantidad"]
    resultado.monto_total = totales["monto"]
    resultado.mas_vendidos = mas_vendidos(almacen, inicio, fin)
    resultado.menos_vendidos = menos_vendidos(almacen, inicio, fin)
    resultado.unidades = _detalles_vigentes(almacen, inicio, fin).aggregate(
        unidades=Sum("cantidad")
    )["unidades"]
    resultado.sin_ventas = sin_ventas(almacen, inicio, fin)
    resultado.por_categoria = ventas_por_categoria(almacen, inicio, fin)
    if periodo.tipo == TipoPeriodo.ANIO:
        resultado.por_dia = ventas_por_mes(almacen, resultado.desde, resultado.hasta)
    elif periodo.tipo == TipoPeriodo.SEMANA:
        resultado.por_dia = _ventas_por_dia_de_la_semana(
            almacen, resultado.desde, resultado.hasta
        )
    else:
        resultado.por_dia = ventas_por_dia(almacen, resultado.desde, resultado.hasta)
    if periodo.tipo != TipoPeriodo.SEMANA:  # en una semana cada día aparece una vez
        resultado.por_dia_semana = ventas_por_dia_semana(
            almacen, resultado.desde, resultado.hasta
        )
    resultado.por_franja = ventas_por_franja(almacen, inicio, fin)
    resultado.comparacion, resultado.motivo_sin_comparacion = comparacion(
        almacen, periodo, hoy, inicio_registros
    )
    if resultado.motivo_sin_comparacion is None:
        resultado.variacion = resultado.comparacion[-1]["variacion"]
    return resultado


def reporte_mensual(almacen, mes, hoy=None):
    """Arma el reporte de `mes` (cualquier día del mes). No registra el acceso."""
    return reporte(almacen, Periodo.que_contiene(TipoPeriodo.MES, mes), hoy)


@transaction.atomic
def consultar_reporte(*, almacen, usuario, periodo, hoy=None):
    """
    CU-04: arma el reporte y registra el acceso (indicador «uso de la reportería»), con
    el tipo de período. Abrir el reporte de un mes cerrado da por vista su alerta de
    cierre de mes.
    """
    if usuario.id_almacen_id != almacen.pk:
        raise ReglaDeNegocioError("Ese usuario no pertenece a este almacén.")
    resultado = reporte(almacen, periodo, hoy)
    AccesoReporte.objects.del_almacen(almacen).create(
        id_usuario=usuario, mes_consultado=periodo.inicio, tipo_periodo=periodo.tipo
    )
    if periodo.tipo == TipoPeriodo.MES:
        alertas_pendientes(almacen).filter(
            tipo=TipoAlerta.CIERRE_MES, fecha_referencia=periodo.inicio
        ).update(fecha_vista=timezone.now(), id_usuario_vista=usuario)
    return resultado


def consultar_reporte_mensual(*, almacen, usuario, mes, hoy=None):
    return consultar_reporte(
        almacen=almacen,
        usuario=usuario,
        periodo=Periodo.que_contiene(TipoPeriodo.MES, mes),
        hoy=hoy,
    )


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
