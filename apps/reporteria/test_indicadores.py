"""
Indicadores de §7: servicios (unitarias) y pantalla (integración). Todos los datos
son FICTICIOS, creados sólo para pruebas: no provienen del almacén piloto.
"""

from datetime import date, timedelta

import pytest

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.servicios import crear_almacen
from apps.almacenes.templatetags.formato import duracion
from apps.inventario.models import MotivoAjuste, MovimientoStock, TipoMovimiento
from apps.reporteria.models import AccesoReporte
from apps.reporteria.servicios import (
    LINEA_BASE_PENDIENTE,
    exactitud_de_inventario,
    indicadores,
    quiebres_de_stock,
    tiempo_de_registro,
    uso_de_reporteria,
)
from apps.reporteria.test_servicios import dar_de_alta_en, local, producto_ficticio, vender
from apps.usuarios.models import RolUsuario
from apps.ventas.models import EstadoVenta, Venta
from conftest import usuario_de

HOY = date(2026, 10, 16)
SEPTIEMBRE, OCTUBRE = date(2026, 9, 1), date(2026, 10, 1)
URL = "/reportes/indicadores/"


@pytest.fixture
def tienda(almacen):
    return dar_de_alta_en(almacen, date(2026, 1, 1))


def movimiento(almacen, producto, momento, tipo, cantidad, motivo=None):
    return MovimientoStock.objects.del_almacen(almacen).create(
        id_producto=producto,
        id_usuario=usuario_de(almacen),
        tipo=tipo,
        cantidad=cantidad,
        motivo=motivo,
        fecha_hora=momento,
    )


def venta_con_apertura(almacen, momento, segundos, producto):
    venta = vender(almacen, momento, (producto, 1))
    venta.hora_inicio = momento - timedelta(seconds=segundos) if segundos else None
    venta.save(update_fields=["hora_inicio"])
    return venta


@pytest.mark.django_db
class TestTiempoDeRegistro:
    def test_mediana_en_postgresql_y_ventas_sin_medir(self, tienda):
        producto = producto_ficticio(tienda)
        for dia, segundos in [(1, 30), (2, 50), (3, 40), (4, None)]:
            venta_con_apertura(tienda, local(2026, 9, dia, 10, 0), segundos, producto)
        venta_con_apertura(tienda, local(2026, 10, 1, 10, 0), 500, producto)  # otro mes

        tiempo = tiempo_de_registro(tienda, SEPTIEMBRE, OCTUBRE)

        assert tiempo == {"medidas": 3, "sin_medir": 1, "mediana": timedelta(seconds=40)}

    def test_cuenta_las_anuladas(self, tienda):
        producto = producto_ficticio(tienda)
        venta = venta_con_apertura(tienda, local(2026, 9, 5, 10, 0), 60, producto)
        Venta.objects.del_almacen(tienda).filter(pk=venta.pk).update(
            estado=EstadoVenta.ANULADA,
            id_usuario_anulacion=usuario_de(tienda),
            motivo_anulacion="Error ficticio de prueba",
            fecha_anulacion=local(2026, 9, 5, 11, 0),
        )
        assert tiempo_de_registro(tienda, SEPTIEMBRE, OCTUBRE)["medidas"] == 1

    def test_sin_ventas_no_hay_mediana(self, tienda):
        tiempo = tiempo_de_registro(tienda, SEPTIEMBRE, OCTUBRE)
        assert tiempo == {"medidas": 0, "sin_medir": 0, "mediana": None}


@pytest.mark.django_db
class TestQuiebresDeStock:
    def test_llegada_a_cero_y_reposicion(self, tienda):
        pan, leche = producto_ficticio(tienda, "Pan"), producto_ficticio(tienda, "Leche")
        # Pan: 5 → 0 el día 3, repuesto 2 días después; vuelve a 0 el día 10 sin reponer.
        movimiento(tienda, pan, local(2026, 8, 30, 9, 0), TipoMovimiento.ENTRADA, 5)
        movimiento(tienda, pan, local(2026, 9, 3, 9, 0), TipoMovimiento.SALIDA, 5)
        movimiento(tienda, pan, local(2026, 9, 5, 9, 0), TipoMovimiento.ENTRADA, 2)
        movimiento(tienda, pan, local(2026, 9, 10, 9, 0), TipoMovimiento.SALIDA, 2)
        # Leche: 6a (ajuste +1 y salida 3 de un stock de 2) → 0, repuesta 1 día después.
        movimiento(tienda, leche, local(2026, 9, 1, 8, 0), TipoMovimiento.ENTRADA, 2)
        movimiento(
            tienda,
            leche,
            local(2026, 9, 7, 12, 0),
            TipoMovimiento.AJUSTE,
            1,
            MotivoAjuste.VENTA_SIN_STOCK,
        )
        movimiento(tienda, leche, local(2026, 9, 7, 12, 0), TipoMovimiento.SALIDA, 3)
        movimiento(tienda, leche, local(2026, 9, 8, 12, 0), TipoMovimiento.ENTRADA, 10)

        assert quiebres_de_stock(tienda, SEPTIEMBRE, OCTUBRE) == {
            "quiebres": 3,
            "productos": 2,
            "sin_reponer": 1,
            "mediana_reposicion": timedelta(days=1.5),  # mediana de 2 días y 1 día
        }

    def test_la_historia_anterior_cuenta_para_el_stock_pero_no_el_quiebre(self, tienda):
        pan = producto_ficticio(tienda, "Pan")
        movimiento(tienda, pan, local(2026, 8, 1, 9, 0), TipoMovimiento.ENTRADA, 4)
        movimiento(tienda, pan, local(2026, 8, 20, 9, 0), TipoMovimiento.SALIDA, 4)  # agosto
        movimiento(tienda, pan, local(2026, 9, 2, 9, 0), TipoMovimiento.ENTRADA, 3)
        movimiento(tienda, pan, local(2026, 9, 9, 9, 0), TipoMovimiento.SALIDA, 1)  # queda 2

        quiebres = quiebres_de_stock(tienda, SEPTIEMBRE, OCTUBRE)

        assert (quiebres["quiebres"], quiebres["mediana_reposicion"]) == (0, None)

    def test_no_mira_otro_almacen(self, tienda):
        otro_almacen = crear_almacen(
            razon_social="Otro Almacén Ficticio", rut="76000002-2", plan="basico"
        )
        ajeno = producto_ficticio(otro_almacen, "Ajeno")
        movimiento(otro_almacen, ajeno, local(2026, 9, 1, 9, 0), TipoMovimiento.ENTRADA, 1)
        movimiento(otro_almacen, ajeno, local(2026, 9, 2, 9, 0), TipoMovimiento.SALIDA, 1)
        assert quiebres_de_stock(tienda, SEPTIEMBRE, OCTUBRE)["quiebres"] == 0


@pytest.mark.django_db
class TestExactitudYUso:
    def test_exactitud_excluye_la_alta_rapida(self, tienda):
        pan, leche = producto_ficticio(tienda, "Pan"), producto_ficticio(tienda, "Leche")
        ajuste = TipoMovimiento.AJUSTE
        movimiento(
            tienda, pan, local(2026, 9, 3, 9, 0), ajuste, -2, MotivoAjuste.PRODUCTO_VENCIDO
        )
        movimiento(
            tienda, pan, local(2026, 9, 4, 9, 0), ajuste, 3, MotivoAjuste.DIFERENCIA_INVENTARIO
        )
        movimiento(tienda, leche, local(2026, 9, 5, 9, 0), ajuste, 4, MotivoAjuste.ALTA_RAPIDA)
        movimiento(
            tienda, leche, local(2026, 8, 5, 9, 0), ajuste, 1, MotivoAjuste.PRODUCTO_DANADO
        )

        assert exactitud_de_inventario(tienda, SEPTIEMBRE, OCTUBRE) == {
            "ajustes": 2,
            "unidades": 5,  # |−2| + |3|
            "productos": 1,
        }

    def test_uso_cuenta_consultas_y_dias_en_hora_local(self, tienda):
        admin = usuario_de(tienda)
        # 23:30 del 30-09 en Santiago ya es 1-10 en UTC: debe contar en septiembre.
        for momento in [
            local(2026, 9, 2, 9, 0),
            local(2026, 9, 2, 18, 0),
            local(2026, 9, 30, 23, 30),
        ]:
            AccesoReporte.objects.del_almacen(tienda).create(
                id_usuario=admin, mes_consultado=SEPTIEMBRE, fecha_hora=momento
            )
        assert uso_de_reporteria(tienda, SEPTIEMBRE, OCTUBRE) == {"consultas": 3, "dias": 2}


@pytest.mark.django_db
class TestIndicadores:
    def test_mes_en_curso_hasta_hoy_y_linea_base_sin_medir(self, tienda):
        resultado = indicadores(tienda, OCTUBRE, hoy=HOY)
        assert resultado.en_curso and resultado.mes_parcial
        assert resultado.hasta == date(2026, 10, 17)
        assert resultado.linea_base == LINEA_BASE_PENDIENTE
        assert not resultado.hay_movimientos

    def test_mes_futuro(self, tienda):
        with pytest.raises(ReglaDeNegocioError, match="todavía no empieza"):
            indicadores(tienda, date(2026, 11, 1), hoy=HOY)

    def test_ver_indicadores_no_registra_uso(self, tienda):
        indicadores(tienda, SEPTIEMBRE, hoy=HOY)
        assert not AccesoReporte.objects.del_almacen(tienda).exists()


@pytest.mark.parametrize(
    "segundos, texto",
    [
        (40.4, "40 s"),
        (95, "1 min 35 s"),
        (120, "2 min"),
        (3 * 3600 + 600, "3 h 10 min"),
        (86400, "1 día"),
        (2 * 86400 + 4 * 3600 + 59, "2 días 4 h"),
    ],
)
def test_filtro_duracion(segundos, texto):
    assert duracion(timedelta(seconds=segundos)) == texto


@pytest.mark.django_db
class TestPantallaIndicadores:
    def test_vendedor_no_los_ve(self, client, tienda):
        client.force_login(usuario_de(tienda, RolUsuario.VENDEDOR))
        assert client.get(URL).status_code == 403

    def test_sin_datos_lo_dice_y_no_muestra_ceros_inventados(self, client, tienda):
        client.force_login(usuario_de(tienda))
        html = client.get(URL, {"mes": "2026-09"}).content.decode()
        assert "Indicadores de septiembre 2026" in html
        assert html.count(LINEA_BASE_PENDIENTE) == 4
        assert "No hay ventas en el período" in html
        assert "No hubo movimientos de stock en el período" in html

    def test_con_datos(self, client, tienda):
        producto = producto_ficticio(tienda)
        venta_con_apertura(tienda, local(2026, 9, 2, 10, 0), 95, producto)
        movimiento(tienda, producto, local(2026, 9, 1, 9, 0), TipoMovimiento.ENTRADA, 1)
        movimiento(tienda, producto, local(2026, 9, 2, 10, 0), TipoMovimiento.SALIDA, 1)
        client.force_login(usuario_de(tienda))
        html = client.get(URL, {"mes": "2026-09"}).content.decode()
        assert "1 min 35 s" in html
        assert "sin reponer" in html

    def test_mes_invalido_vuelve_al_mes_actual(self, client, tienda):
        client.force_login(usuario_de(tienda))
        assert client.get(URL, {"mes": "2099-01"}).status_code == 302
