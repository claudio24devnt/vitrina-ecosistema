"""
Ganancia del período (2026-11-19): se calcula con el costo copiado en cada venta y nunca
toma un costo faltante como cero. Todos los datos son FICTICIOS, creados sólo para
pruebas: no provienen del almacén piloto ni de ningún almacén real.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.almacenes.servicios import crear_almacen
from apps.inventario.models import Producto
from apps.reporteria.models import TipoPeriodo
from apps.reporteria.periodos import Periodo
from apps.reporteria.servicios import reporte, reporte_mensual
from apps.reporteria.test_servicios import dar_de_alta_en, local, producto_ficticio, vender
from apps.ventas.models import DetalleVenta
from conftest import usuario_de

HOY = date(2026, 10, 16)
SEPTIEMBRE = date(2026, 9, 1)


@pytest.fixture
def tienda(almacen):
    return dar_de_alta_en(almacen, date(2026, 1, 1))


def vender_con_costo(almacen, momento, *lineas):
    """Venta con líneas (producto, cantidad, costo_unitario); costo None = sin costo."""
    venta = vender(almacen, momento, *[(p, c) for p, c, _ in lineas])
    for producto, _, costo in lineas:
        DetalleVenta.objects.del_almacen(almacen).filter(
            id_venta=venta, id_producto=producto
        ).update(costo_unitario=costo)
    return venta


@pytest.mark.django_db
class TestGanancia:
    def test_ganancia_margen_y_costo_con_todo_costeado(self, tienda):
        a = producto_ficticio(tienda, "A Ficticio", precio=1000)
        b = producto_ficticio(tienda, "B Ficticio", precio=500)
        vender_con_costo(tienda, local(2026, 9, 10, 10), (a, 2, 700), (b, 4, 300))
        g = reporte_mensual(tienda, SEPTIEMBRE, HOY).ganancia
        # Vendido 4.000; costo 2·700 + 4·300 = 2.600; ganancia 1.400; margen 35 %.
        assert (g["monto"], g["costo"], g["margen"]) == (
            Decimal("1400"),
            Decimal("2600"),
            Decimal("35.0"),
        )
        assert g["completa"] and g["cobertura"] == Decimal("100.0")

    def test_usa_el_costo_de_la_venta_no_el_de_hoy(self, tienda):
        a = producto_ficticio(tienda, precio=1000, costo=Decimal("600"))
        vender_con_costo(tienda, local(2026, 9, 10, 10), (a, 1, 600))
        Producto.objects.del_almacen(tienda).filter(pk=a.pk).update(costo=900)
        assert reporte_mensual(tienda, SEPTIEMBRE, HOY).ganancia["monto"] == Decimal("400")

    def test_lo_sin_costo_queda_fuera_y_se_informa(self, tienda):
        a = producto_ficticio(tienda, "A Ficticio", precio=1000)
        b = producto_ficticio(tienda, "B Ficticio", precio=1000)
        c = producto_ficticio(tienda, "C Ficticio", precio=500)
        vender_con_costo(
            tienda, local(2026, 9, 10, 10), (a, 3, 600), (b, 1, None), (c, 2, None)
        )
        g = reporte_mensual(tienda, SEPTIEMBRE, HOY).ganancia
        assert g["monto"] == Decimal("1200")  # sólo A: 3.000 − 1.800; B y C no valen cero
        assert g["cobertura"] == Decimal("60.0")  # 3.000 de 5.000
        assert (g["completa"], g["productos_sin_costo"]) == (False, 2)

    def test_sin_ningun_costo_no_muestra_una_ganancia_en_cero(self, tienda):
        a = producto_ficticio(tienda)
        vender(tienda, local(2026, 9, 10, 10), (a, 1))
        g = reporte_mensual(tienda, SEPTIEMBRE, HOY).ganancia
        assert not g["hay_costos"]
        assert g["monto"] is None and g["margen"] is None

    def test_vender_bajo_el_costo_da_ganancia_negativa(self, tienda):
        a = producto_ficticio(tienda, precio=500)
        vender_con_costo(tienda, local(2026, 9, 10, 10), (a, 2, 700))
        g = reporte_mensual(tienda, SEPTIEMBRE, HOY).ganancia
        assert (g["monto"], g["margen"]) == (Decimal("-400"), Decimal("-40.0"))

    def test_una_venta_anulada_no_suma_ganancia(self, tienda):
        from apps.ventas.servicios import anular_venta

        a = producto_ficticio(tienda, precio=1000)
        vender_con_costo(tienda, local(2026, 9, 10, 10), (a, 1, 600))
        anulada = vender_con_costo(tienda, local(2026, 9, 11, 10), (a, 5, 600))
        anular_venta(
            almacen=tienda,
            venta=anulada,
            usuario=usuario_de(tienda),
            motivo="Error de digitación",
            momento=local(2026, 9, 11, 10, 5),
        )
        assert reporte_mensual(tienda, SEPTIEMBRE, HOY).ganancia["monto"] == Decimal("400")

    def test_no_mezcla_otro_almacen(self, tienda):
        ajeno = dar_de_alta_en(
            crear_almacen(
                razon_social="Almacén Ficticio Ajeno", rut="76000003-3", plan="basico"
            ),
            date(2026, 1, 1),
        )
        propio = producto_ficticio(tienda, precio=1000)
        otro = producto_ficticio(ajeno, precio=1000)
        vender_con_costo(tienda, local(2026, 9, 10, 10), (propio, 1, 600))
        vender_con_costo(ajeno, local(2026, 9, 10, 10), (otro, 50, 10))
        for periodo in (
            Periodo(TipoPeriodo.SEMANA, date(2026, 9, 7)),
            Periodo(TipoPeriodo.MES, SEPTIEMBRE),
            Periodo(TipoPeriodo.ANIO, date(2026, 1, 1)),
        ):
            g = reporte(tienda, periodo, HOY).ganancia
            assert (g["monto"], g["costo"]) == (Decimal("400"), Decimal("600"))


@pytest.mark.django_db
class TestStockParadoACosto:
    def test_valora_a_costo_y_cuenta_los_sin_costo(self, tienda):
        vendido = producto_ficticio(tienda, "Vendido Ficticio")
        producto_ficticio(tienda, "Quieto Ficticio", costo=Decimal("300"), stock_actual=4)
        producto_ficticio(tienda, "Sin costo Ficticio", stock_actual=2)
        Producto.objects.del_almacen(tienda).update(fecha_creacion=local(2026, 1, 1, 0))
        vender(tienda, local(2026, 9, 10, 10), (vendido, 1))
        parado = reporte_mensual(tienda, SEPTIEMBRE, HOY).sin_ventas
        assert parado["valor"] == Decimal("6000")  # 6 unidades a $1.000
        assert parado["valor_costo"] == Decimal("1200")  # sólo las 4 con costo
        assert parado["sin_costo"] == 1


@pytest.mark.django_db
class TestPantallaDeGanancia:
    def _ver(self, client, tienda):
        client.force_login(usuario_de(tienda))
        return client.get(
            reverse("reporteria:reporte_mensual") + "?mes=2026-09"
        ).content.decode()

    def test_sin_costos_invita_a_anotarlos(self, client, tienda):
        vender(tienda, local(2026, 9, 10, 10), (producto_ficticio(tienda), 1))
        html = self._ver(client, tienda)
        assert "Para ver la ganancia, anota el costo" in html
        assert "?costo=sin" in html

    def test_con_costos_parciales_muestra_ganancia_y_cobertura(self, client, tienda):
        a = producto_ficticio(tienda, "A Ficticio", precio=1000)
        b = producto_ficticio(tienda, "B Ficticio", precio=1000)
        vender_con_costo(tienda, local(2026, 9, 10, 10), (a, 3, 600), (b, 2, None))
        html = self._ver(client, tienda)
        assert "$1.200" in html  # ganancia
        assert "Ganancia calculada sobre el 60,0 % de lo vendido" in html
        assert "1 producto vendido no tenía costo anotado" in html

    def test_el_vendedor_no_ve_el_reporte(self, client, tienda):
        client.force_login(usuario_de(tienda, "vendedor"))
        respuesta = client.get(reverse("reporteria:reporte_mensual") + "?mes=2026-09")
        assert respuesta.status_code == 403
