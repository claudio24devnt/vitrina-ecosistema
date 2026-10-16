"""
Unitarias de servicios: reporte mensual (CU-04) y alertas (CU-05, cierre de mes).
Todos los datos son FICTICIOS, creados sólo para pruebas: no provienen del almacén
piloto ni de ningún almacén real.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN, Almacen
from apps.almacenes.servicios import crear_almacen
from apps.inventario.models import Producto
from apps.reporteria.models import AccesoReporte, Alerta, TipoAlerta
from apps.reporteria.servicios import (
    TOPE_MAS_VENDIDOS,
    alertar_stock_bajo,
    alertas_del_panel,
    avisar_cierre_mes,
    consultar_reporte_mensual,
    marcar_alerta_vista,
    meses_disponibles,
    reporte_mensual,
)
from apps.usuarios.models import RolUsuario
from apps.ventas.models import DetalleVenta, MedioPago, Venta
from apps.ventas.servicios import anular_venta
from conftest import usuario_de

HOY = date(2026, 10, 16)  # viernes; octubre en curso
SEPTIEMBRE = date(2026, 9, 1)
AGOSTO = date(2026, 8, 1)


def local(*partes):
    """Instante en hora de Santiago, p. ej. local(2026, 9, 7, 23, 30)."""
    return datetime(*partes, tzinfo=ZONA_HORARIA_ALMACEN)


def dar_de_alta_en(almacen, fecha):
    """Simula que el almacén empezó a usar el sistema en `fecha`."""
    Almacen.sin_aislamiento.filter(pk=almacen.pk).update(
        fecha_alta=datetime.combine(fecha, datetime.min.time(), tzinfo=ZONA_HORARIA_ALMACEN)
    )
    almacen.refresh_from_db()
    return almacen


def producto_ficticio(almacen, nombre="Producto Ficticio", codigo=None, precio=1000, **extra):
    total = Producto.objects.del_almacen(almacen).count()
    return Producto.objects.del_almacen(almacen).create(
        codigo_barras=codigo or f"99{total:011d}",
        nombre=nombre,
        precio=Decimal(precio),
        **extra,
    )


def vender(almacen, momento, *lineas, usuario=None):
    """Venta vigente confirmada en `momento`, con líneas (producto, cantidad)."""
    usuario = usuario or usuario_de(almacen, RolUsuario.VENDEDOR)
    total = sum(producto.precio * cantidad for producto, cantidad in lineas)
    venta = Venta.objects.del_almacen(almacen).create(
        id_usuario=usuario, total=total, medio_pago=MedioPago.EFECTIVO, fecha_hora=momento
    )
    for producto, cantidad in lineas:
        DetalleVenta.objects.del_almacen(almacen).create(
            id_venta=venta,
            id_producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=producto.precio * cantidad,
        )
    return venta


@pytest.fixture
def tienda(almacen):
    """Almacén ficticio en uso desde antes de los meses que se consultan."""
    return dar_de_alta_en(almacen, date(2026, 1, 1))


@pytest.fixture
def producto(tienda):
    return producto_ficticio(tienda)


@pytest.mark.django_db
class TestMesSinVentas:
    def test_informa_ausencia_de_datos(self, tienda):
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.hay_ventas is False
        assert reporte.mas_vendidos == reporte.por_dia_semana == reporte.por_franja == []
        assert reporte.comparacion == []

    def test_las_anuladas_no_cuentan(self, tienda, producto):
        venta = vender(tienda, local(2026, 9, 10, 12), (producto, 1))
        anular_venta(
            almacen=tienda,
            venta=venta,
            usuario=usuario_de(tienda),
            motivo="Error de digitación",
            momento=local(2026, 9, 10, 12, 5),
        )
        assert reporte_mensual(tienda, SEPTIEMBRE, HOY).hay_ventas is False

    def test_mes_futuro_se_rechaza(self, tienda):
        with pytest.raises(ReglaDeNegocioError, match="todavía no empieza"):
            reporte_mensual(tienda, date(2026, 11, 1), HOY)


@pytest.mark.django_db
class TestLimitesDelMesEnHoraLocal:
    def test_las_23_30_del_ultimo_dia_es_del_mes_aunque_en_utc_sea_el_siguiente(
        self, tienda, producto
    ):
        momento = local(2026, 9, 30, 23, 30)
        assert momento.astimezone(UTC).month == 10
        vender(tienda, momento, (producto, 1))
        assert reporte_mensual(tienda, SEPTIEMBRE, HOY).cantidad_ventas == 1
        assert reporte_mensual(tienda, date(2026, 10, 1), HOY).hay_ventas is False

    def test_la_medianoche_del_dia_1_es_del_mes_nuevo(self, tienda, producto):
        vender(tienda, local(2026, 10, 1, 0, 0), (producto, 1))
        assert reporte_mensual(tienda, SEPTIEMBRE, HOY).hay_ventas is False
        assert reporte_mensual(tienda, date(2026, 10, 1), HOY).cantidad_ventas == 1

    def test_totales_del_mes(self, tienda, producto):
        vender(tienda, local(2026, 9, 3, 10), (producto, 2))
        vender(tienda, local(2026, 9, 4, 10), (producto, 3))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert (reporte.cantidad_ventas, reporte.monto_total) == (2, Decimal("5000"))


@pytest.mark.django_db
class TestMasVendidos:
    def test_ordena_por_unidades_y_calcula_participacion(self, tienda):
        pan = producto_ficticio(tienda, "Pan Ficticio", precio=200)
        bebida = producto_ficticio(tienda, "Bebida Ficticia", precio=1500)
        vender(tienda, local(2026, 9, 5, 9), (pan, 6), (bebida, 1))
        vender(tienda, local(2026, 9, 6, 9), (pan, 2), (bebida, 1))

        primero, segundo = reporte_mensual(tienda, SEPTIEMBRE, HOY).mas_vendidos
        assert (primero["nombre"], primero["lugar"], primero["unidades"]) == (
            "Pan Ficticio",
            1,
            8,
        )
        assert primero["monto"] == Decimal("1600")
        assert primero["participacion"] == Decimal("80.0")
        assert (segundo["lugar"], segundo["unidades"], segundo["participacion"]) == (
            2,
            2,
            Decimal("20.0"),
        )

    def test_los_empatados_comparten_lugar(self, tienda):
        a = producto_ficticio(tienda, "A Ficticio")
        b = producto_ficticio(tienda, "B Ficticio")
        c = producto_ficticio(tienda, "C Ficticio")
        vender(tienda, local(2026, 9, 5, 9), (a, 3), (b, 3), (c, 1))
        lugares = [
            (f["nombre"], f["lugar"])
            for f in reporte_mensual(tienda, SEPTIEMBRE, HOY).mas_vendidos
        ]
        assert lugares == [("A Ficticio", 1), ("B Ficticio", 1), ("C Ficticio", 3)]

    def test_corta_en_el_tope_sin_dejar_fuera_a_un_empatado(self, tienda):
        productos = [producto_ficticio(tienda, f"P{i:02d} Ficticio") for i in range(12)]
        # P00 vende 20, P01 19 ... P09 11; P10 empata con P09; P11 queda atrás.
        lineas = [(p, 20 - i) for i, p in enumerate(productos[:10])]
        lineas += [(productos[10], 11), (productos[11], 1)]
        vender(tienda, local(2026, 9, 5, 9), *lineas)

        filas = reporte_mensual(tienda, SEPTIEMBRE, HOY).mas_vendidos
        assert len(filas) == TOPE_MAS_VENDIDOS + 1
        assert [f["lugar"] for f in filas[-2:]] == [10, 10]
        assert "P11 Ficticio" not in [f["nombre"] for f in filas]
        # La participación se calcula sobre todo el mes, no sólo sobre los mostrados.
        assert filas[0]["participacion"] == Decimal("12.0")  # 20 de 167 unidades


@pytest.mark.django_db
class TestPorDiaDeLaSemana:
    def test_usa_el_dia_local_y_no_el_de_utc(self, tienda, producto):
        lunes_de_noche = local(2026, 9, 7, 23, 30)  # en UTC ya es martes
        assert lunes_de_noche.astimezone(UTC).weekday() == 1
        vender(tienda, lunes_de_noche, (producto, 1))
        filas = {f["dia"]: f for f in reporte_mensual(tienda, SEPTIEMBRE, HOY).por_dia_semana}
        assert filas["Lunes"]["cantidad"] == 1
        assert filas["Martes"]["cantidad"] == 0

    def test_promedia_por_las_veces_que_aparece_cada_dia(self, tienda, producto):
        # Septiembre 2026 empieza en martes: trae 5 martes y 5 miércoles, 4 del resto.
        vender(tienda, local(2026, 9, 1, 10), (producto, 10))  # martes, $10.000
        vender(tienda, local(2026, 9, 7, 10), (producto, 8))  # lunes, $8.000
        filas = {f["dia"]: f for f in reporte_mensual(tienda, SEPTIEMBRE, HOY).por_dia_semana}
        assert [f["dias"] for f in filas.values()] == [4, 5, 5, 4, 4, 4, 4]
        assert filas["Martes"]["promedio_diario"] == Decimal("2000")
        assert filas["Lunes"]["promedio_diario"] == Decimal("2000")
        assert filas["Domingo"]["promedio_diario"] == Decimal("0")
        # Mismo promedio: los dos son el día de mayor demanda.
        assert [d for d, f in filas.items() if f["es_mayor"]] == ["Lunes", "Martes"]
        assert filas["Martes"]["participacion"] == Decimal("55.6")

    def test_mes_en_curso_cuenta_solo_los_dias_transcurridos(self, tienda, producto):
        vender(tienda, local(2026, 10, 2, 10), (producto, 1))
        reporte = reporte_mensual(tienda, date(2026, 10, 1), HOY)
        assert (reporte.desde, reporte.ultimo_dia) == (date(2026, 10, 1), HOY)
        assert reporte.mes_parcial and reporte.en_curso
        # Del jueves 1 al viernes 16 de octubre: 3 jueves y 3 viernes, 2 del resto.
        assert [f["dias"] for f in reporte.por_dia_semana] == [2, 2, 2, 3, 3, 2, 2]


@pytest.mark.django_db
class TestPorFranja:
    def test_asigna_franja_en_hora_local_y_lista_todas(self, tienda, producto):
        vender(tienda, local(2026, 9, 5, 7, 0), (producto, 1))  # Mañana
        vender(tienda, local(2026, 9, 5, 22, 30), (producto, 1))  # Resto
        vender(tienda, local(2026, 9, 6, 6, 59), (producto, 1))  # Resto (cruza medianoche)
        filas = reporte_mensual(tienda, SEPTIEMBRE, HOY).por_franja
        assert [(f["franja"], f["cantidad"]) for f in filas] == [
            ("Mañana", 1),
            ("Mediodía", 0),
            ("Tarde", 0),
            ("Noche", 0),
            ("Resto", 2),
        ]
        assert filas[0]["horario"] == "07:00 – 10:59"
        assert [f["franja"] for f in filas if f["es_mayor"]] == ["Resto"]
        assert filas[4]["participacion"] == Decimal("66.7")


@pytest.mark.django_db
class TestComparacionConMesesAnteriores:
    def test_calcula_la_variacion_entre_meses_completos(self, tienda, producto):
        vender(tienda, local(2026, 8, 10, 10), (producto, 10))
        vender(tienda, local(2026, 9, 10, 10), (producto, 15))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.motivo_sin_comparacion is None
        assert reporte.variacion == Decimal("50.0")
        ultimos = [(f["mes"], f["monto"], f["variacion"]) for f in reporte.comparacion[-2:]]
        assert ultimos == [
            (AGOSTO, Decimal("10000"), None),  # julio no tuvo ventas
            (SEPTIEMBRE, Decimal("15000"), Decimal("50.0")),
        ]

    def test_muestra_seis_meses_sin_ir_antes_del_inicio(self, tienda, producto):
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        meses = [f["mes"] for f in reporte_mensual(tienda, SEPTIEMBRE, HOY).comparacion]
        assert meses == [date(2026, m, 1) for m in range(4, 10)]

        dar_de_alta_en(tienda, date(2026, 8, 1))
        meses = [f["mes"] for f in reporte_mensual(tienda, SEPTIEMBRE, HOY).comparacion]
        assert meses == [AGOSTO, SEPTIEMBRE]

    def test_sin_ventas_el_mes_anterior_omite_e_indica_el_motivo(self, tienda, producto):
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.variacion is None
        assert reporte.motivo_sin_comparacion == (
            "No hay ventas registradas en agosto 2026 para comparar."
        )

    def test_no_compara_con_un_mes_no_consecutivo(self, tienda, producto):
        vender(tienda, local(2026, 7, 10, 10), (producto, 1))
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.comparacion[-1]["variacion"] is None
        assert "agosto 2026" in reporte.motivo_sin_comparacion

    def test_mes_en_curso_no_se_compara(self, tienda, producto):
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        vender(tienda, local(2026, 10, 2, 10), (producto, 1))
        reporte = reporte_mensual(tienda, date(2026, 10, 1), HOY)
        assert reporte.variacion is None
        assert reporte.motivo_sin_comparacion.startswith("Octubre 2026 todavía no termina")
        assert reporte.comparacion[-1]["completo"] is False

    def test_mes_base_incompleto_no_sirve_de_base(self, tienda, producto):
        dar_de_alta_en(tienda, date(2026, 8, 20))
        vender(tienda, local(2026, 8, 25, 10), (producto, 1))
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.variacion is None
        assert reporte.motivo_sin_comparacion == (
            "El almacén empezó a registrar en TivoScanea el 20-08-2026: agosto 2026 no "
            "está completo y no sirve como base."
        )

    def test_mes_consultado_incompleto_no_se_compara(self, tienda, producto):
        dar_de_alta_en(tienda, date(2026, 9, 14))
        vender(tienda, local(2026, 9, 20, 10), (producto, 1))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.mes_parcial and not reporte.en_curso
        assert reporte.desde == date(2026, 9, 14)
        assert "septiembre 2026 no está completo y no se compara" in (
            reporte.motivo_sin_comparacion
        )

    def test_una_venta_anterior_al_alta_adelanta_el_inicio(self, tienda, producto):
        dar_de_alta_en(tienda, date(2026, 9, 14))
        vender(tienda, local(2026, 8, 31, 10), (producto, 1))  # carga anterior al alta
        assert reporte_mensual(tienda, SEPTIEMBRE, HOY).desde == SEPTIEMBRE


@pytest.mark.django_db
class TestCalculoEnLaBaseDeDatos:
    def test_la_cantidad_de_consultas_no_crece_con_las_ventas(
        self, tienda, producto, django_assert_max_num_queries
    ):
        for dia in range(1, 31):
            vender(tienda, local(2026, 9, dia, 12), (producto, 1))
        vender(tienda, local(2026, 8, 3, 12), (producto, 1))
        # Inicio de registros, totales, más vendidos, día, franja (+ franjas), meses.
        with django_assert_max_num_queries(7):
            reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.cantidad_ventas == 30


@pytest.mark.django_db
class TestAislamientoDelReporte:
    def test_un_almacen_no_ve_las_ventas_del_otro(self, tienda, producto):
        otro = dar_de_alta_en(
            crear_almacen(razon_social="Otro Ficticio", rut="76000008-8", plan="basico"),
            date(2026, 1, 1),
        )
        vender(otro, local(2026, 9, 10, 10), (producto_ficticio(otro, "Ajeno Ficticio"), 50))
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        reporte = reporte_mensual(tienda, SEPTIEMBRE, HOY)
        assert reporte.cantidad_ventas == 1
        assert [f["nombre"] for f in reporte.mas_vendidos] == ["Producto Ficticio"]


@pytest.mark.django_db
class TestConsultarReporte:
    def test_registra_el_acceso_con_el_primer_dia_del_mes(self, tienda):
        admin = usuario_de(tienda)
        consultar_reporte_mensual(
            almacen=tienda, usuario=admin, mes=date(2026, 9, 17), hoy=HOY
        )
        acceso = AccesoReporte.objects.del_almacen(tienda).get()
        assert (acceso.id_usuario, acceso.mes_consultado) == (admin, SEPTIEMBRE)

    def test_registra_el_acceso_aunque_el_mes_no_tenga_ventas(self, tienda):
        consultar_reporte_mensual(
            almacen=tienda, usuario=usuario_de(tienda), mes=AGOSTO, hoy=HOY
        )
        assert AccesoReporte.objects.del_almacen(tienda).count() == 1

    def test_mes_futuro_no_registra_acceso(self, tienda):
        with pytest.raises(ReglaDeNegocioError):
            consultar_reporte_mensual(
                almacen=tienda, usuario=usuario_de(tienda), mes=date(2027, 1, 1), hoy=HOY
            )
        assert AccesoReporte.objects.del_almacen(tienda).count() == 0

    def test_usuario_de_otro_almacen_se_rechaza(self, tienda, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            consultar_reporte_mensual(almacen=tienda, usuario=datos_b.admin, mes=SEPTIEMBRE)

    def test_abrir_el_reporte_da_por_visto_su_cierre_de_mes(self, tienda, producto):
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        aviso, _ = avisar_cierre_mes(tienda, date(2026, 10, 1))
        admin = usuario_de(tienda)
        consultar_reporte_mensual(almacen=tienda, usuario=admin, mes=SEPTIEMBRE, hoy=HOY)
        aviso.refresh_from_db()
        assert aviso.id_usuario_vista == admin and aviso.fecha_vista is not None

    def test_meses_disponibles_desde_el_inicio_hasta_hoy(self, tienda):
        dar_de_alta_en(tienda, date(2026, 8, 20))
        assert meses_disponibles(tienda, HOY) == [date(2026, 10, 1), SEPTIEMBRE, AGOSTO]


@pytest.mark.django_db
class TestAlertaStockBajo:
    def test_genera_una_alerta_si_hay_productos_en_o_bajo_el_minimo(self, tienda):
        producto_ficticio(tienda, "En el mínimo", stock_actual=2, stock_minimo=2)
        producto_ficticio(tienda, "Bajo el mínimo", stock_actual=0, stock_minimo=1)
        producto_ficticio(tienda, "Sobre el mínimo", stock_actual=5, stock_minimo=1)
        alerta, creada = alertar_stock_bajo(tienda, HOY)
        assert creada
        assert (alerta.tipo, alerta.fecha_referencia) == (TipoAlerta.STOCK_BAJO, HOY)
        assert alerta.mensaje.startswith("Hay 2 productos con stock bajo el mínimo")

    def test_sin_productos_bajo_el_minimo_no_genera_alerta(self, tienda):
        producto_ficticio(tienda, stock_actual=5, stock_minimo=1)
        assert alertar_stock_bajo(tienda, HOY) == (None, False)
        assert not Alerta.objects.del_almacen(tienda).exists()

    def test_es_idempotente_en_el_dia(self, tienda):
        producto_ficticio(tienda, stock_actual=0, stock_minimo=1)
        primera, _ = alertar_stock_bajo(tienda, HOY)
        segunda, creada = alertar_stock_bajo(tienda, HOY)
        assert segunda == primera and not creada
        assert Alerta.objects.del_almacen(tienda).count() == 1

    def test_el_panel_muestra_solo_la_revision_mas_reciente(self, tienda):
        producto_ficticio(tienda, stock_actual=0, stock_minimo=1)
        alertar_stock_bajo(tienda, HOY - timedelta(days=1))
        hoy, _ = alertar_stock_bajo(tienda, HOY)
        assert alertas_del_panel(tienda) == [hoy]

    def test_el_umbral_no_cruza_almacenes(self, tienda, datos_b):
        producto_ficticio(datos_b.almacen, stock_actual=0, stock_minimo=5)
        assert alertar_stock_bajo(tienda, HOY) == (None, False)


@pytest.mark.django_db
class TestAvisoCierreDeMes:
    def test_avisa_el_mes_anterior_con_ventas(self, tienda, producto):
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        aviso, creado = avisar_cierre_mes(tienda, date(2026, 10, 1))
        assert creado
        assert (aviso.tipo, aviso.fecha_referencia) == (TipoAlerta.CIERRE_MES, SEPTIEMBRE)
        assert aviso.mensaje == "Ya está disponible el reporte de septiembre 2026."

    def test_cruza_el_anio(self, tienda, producto):
        vender(tienda, local(2026, 12, 31, 23, 50), (producto, 1))
        aviso, _ = avisar_cierre_mes(tienda, date(2027, 1, 1))
        assert aviso.fecha_referencia == date(2026, 12, 1)

    def test_mes_sin_ventas_no_avisa(self, tienda):
        assert avisar_cierre_mes(tienda, date(2026, 10, 1)) == (None, False)

    def test_es_idempotente(self, tienda, producto):
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        avisar_cierre_mes(tienda, date(2026, 10, 1))
        _, creado = avisar_cierre_mes(tienda, date(2026, 10, 2))
        assert not creado
        assert Alerta.objects.del_almacen(tienda).count() == 1


@pytest.mark.django_db
class TestMarcarAlertaVista:
    def test_stock_bajo_se_lleva_las_revisiones_anteriores(self, tienda):
        producto_ficticio(tienda, stock_actual=0, stock_minimo=1)
        ayer, _ = alertar_stock_bajo(tienda, HOY - timedelta(days=1))
        hoy, _ = alertar_stock_bajo(tienda, HOY)
        assert marcar_alerta_vista(almacen=tienda, alerta=hoy, usuario=usuario_de(tienda)) == 2
        assert alertas_del_panel(tienda) == []

    def test_cierre_de_mes_marca_solo_esa(self, tienda, producto):
        vender(tienda, local(2026, 8, 10, 10), (producto, 1))
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        agosto, _ = avisar_cierre_mes(tienda, date(2026, 9, 1))
        septiembre, _ = avisar_cierre_mes(tienda, date(2026, 10, 1))
        marcar_alerta_vista(almacen=tienda, alerta=septiembre, usuario=usuario_de(tienda))
        assert alertas_del_panel(tienda) == [agosto]

    def test_alerta_de_otro_almacen_se_rechaza(self, tienda, datos_b):
        producto_ficticio(datos_b.almacen, stock_actual=0, stock_minimo=5)
        ajena, _ = alertar_stock_bajo(datos_b.almacen, HOY)
        with pytest.raises(ReglaDeNegocioError):
            marcar_alerta_vista(almacen=tienda, alerta=ajena, usuario=usuario_de(tienda))


@pytest.mark.django_db
class TestRestriccionesDeAlerta:
    def _alerta(self, almacen, **campos):
        datos = {"tipo": TipoAlerta.STOCK_BAJO, "fecha_referencia": HOY, "mensaje": "Ficticia"}
        datos.update(campos)
        return Alerta.objects.del_almacen(almacen).create(**datos)

    def test_tipo_fuera_de_la_lista(self, tienda):
        with pytest.raises(IntegrityError):
            self._alerta(tienda, tipo="otra")

    def test_vista_sin_usuario(self, tienda):
        with pytest.raises(IntegrityError):
            self._alerta(tienda, fecha_vista=timezone.now())

    def test_una_por_tipo_y_fecha(self, tienda):
        self._alerta(tienda)
        with pytest.raises(IntegrityError):
            self._alerta(tienda)
