"""Pruebas de servicio de CU-02 (registrar venta) y CU-03 (anular venta)."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN
from apps.inventario import servicios as servicios_inventario
from apps.inventario.models import MotivoAjuste, MovimientoStock, Producto, TipoMovimiento
from apps.inventario.servicios import registrar_ajuste_por_conteo, registrar_producto
from apps.reporteria.servicios import ajustes_de_exactitud
from apps.ventas.models import DetalleVenta, EstadoVenta, MedioPago, Venta
from apps.ventas.servicios import (
    LineaVenta,
    StockInsuficienteError,
    anular_venta,
    registrar_venta,
)


def _vender(datos, lineas, **cambios):
    valores = {
        "almacen": datos.almacen,
        "usuario": datos.vendedor,
        "lineas": lineas,
        "medio_pago": MedioPago.EFECTIVO,
    }
    valores.update(cambios)
    return registrar_venta(**valores)


def _movs(datos, **filtro):
    return MovimientoStock.objects.del_almacen(datos.almacen).filter(**filtro)


def _alta_rapida(datos, codigo="7809990000011"):
    """Lo que hace la caja en CU-02 2a: sólo código, nombre y precio."""
    return registrar_producto(
        almacen=datos.almacen,
        usuario=datos.vendedor,
        codigo_barras=codigo,
        nombre="Producto Nacido en Caja",
        precio=Decimal("650"),
    )


@pytest.mark.django_db
class TestRegistrarVenta:
    def test_venta_con_stock_suficiente(self, datos_a):
        venta = _vender(datos_a, [LineaVenta(datos_a.producto.pk, 3)])
        datos_a.producto.refresh_from_db()
        assert venta.total == Decimal("3000")
        assert datos_a.producto.stock_actual == 7
        (detalle,) = DetalleVenta.objects.del_almacen(datos_a.almacen).filter(id_venta=venta)
        assert (detalle.cantidad, detalle.precio_unitario, detalle.subtotal) == (
            3,
            Decimal("1000"),
            Decimal("3000"),
        )
        assert detalle.id_almacen_id == venta.id_almacen_id
        (salida,) = _movs(datos_a, id_venta=venta)
        assert (salida.tipo, salida.cantidad, salida.id_usuario) == (
            TipoMovimiento.SALIDA,
            3,
            datos_a.vendedor,
        )
        assert not _movs(datos_a, id_venta=venta, tipo=TipoMovimiento.AJUSTE).exists()

    def test_el_precio_lo_pone_el_servidor(self, datos_a):
        # LineaVenta no lleva precio: el total sale de Producto.precio.
        venta = _vender(datos_a, [LineaVenta(datos_a.producto.pk, 1)])
        assert venta.total == datos_a.producto.precio

    def test_mismo_producto_escaneado_dos_veces_se_agrupa(self, datos_a):
        venta = _vender(
            datos_a, [LineaVenta(datos_a.producto.pk, 1), LineaVenta(datos_a.producto.pk, 2)]
        )
        assert (
            DetalleVenta.objects.del_almacen(datos_a.almacen).get(id_venta=venta).cantidad == 3
        )

    def test_graba_hora_de_inicio_para_el_indicador(self, datos_a):
        inicio = timezone.now() - timedelta(seconds=45)
        venta = _vender(datos_a, [LineaVenta(datos_a.producto.pk, 1)], hora_inicio=inicio)
        assert venta.hora_inicio == inicio
        assert venta.fecha_hora > venta.hora_inicio

    @pytest.mark.parametrize(
        "desfase", [timedelta(minutes=5), -timedelta(hours=13)], ids=["futura", "de_ayer"]
    )
    def test_hora_de_inicio_absurda_se_descarta(self, datos_a, desfase):
        venta = _vender(
            datos_a, [LineaVenta(datos_a.producto.pk, 1)], hora_inicio=timezone.now() + desfase
        )
        assert venta.hora_inicio is None

    @pytest.mark.parametrize(
        "lineas,medio",
        [
            ([], MedioPago.EFECTIVO),
            ([LineaVenta(1, 0)], MedioPago.EFECTIVO),
            ([LineaVenta(1, -2)], MedioPago.EFECTIVO),
            ([LineaVenta(1, 1)], "trueque"),
        ],
        ids=["vacia", "cantidad_cero", "cantidad_negativa", "medio_invalido"],
    )
    def test_datos_invalidos(self, datos_a, lineas, medio):
        with pytest.raises(ReglaDeNegocioError):
            _vender(datos_a, lineas, medio_pago=medio)
        assert Venta.objects.del_almacen(datos_a.almacen).count() == 1  # sólo la de conftest

    def test_producto_de_otro_almacen_no_se_vende(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError, match="ya no existe"):
            _vender(datos_a, [LineaVenta(datos_b.producto.pk, 1)])
        datos_b.producto.refresh_from_db()
        assert datos_b.producto.stock_actual == 10

    def test_usuario_de_otro_almacen_no_vende(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            _vender(datos_a, [LineaVenta(datos_a.producto.pk, 1)], usuario=datos_b.vendedor)


@pytest.mark.django_db
class TestTransaccionUnica:
    def test_si_falla_el_descuento_de_stock_no_queda_nada(self, datos_a, monkeypatch):
        original = servicios_inventario.registrar_movimiento
        ventas_antes = Venta.objects.del_almacen(datos_a.almacen).count()
        movimientos_antes = _movs(datos_a).count()

        def falla_en_la_salida(**kwargs):
            if kwargs["tipo"] == TipoMovimiento.SALIDA:
                raise RuntimeError("falla forzada en el descuento de stock")
            return original(**kwargs)

        monkeypatch.setattr("apps.ventas.servicios.registrar_movimiento", falla_en_la_salida)
        with pytest.raises(RuntimeError):
            # 12 > 10: también intenta un ajuste antes de fallar, que debe revertirse.
            _vender(datos_a, [LineaVenta(datos_a.producto.pk, 12)], confirmar_diferencias=True)

        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10
        assert Venta.objects.del_almacen(datos_a.almacen).count() == ventas_antes
        assert _movs(datos_a).count() == movimientos_antes


@pytest.mark.django_db
class TestDiferenciaDeInventario6a:
    def test_sin_confirmacion_avisa_y_no_escribe_nada(self, datos_a):
        with pytest.raises(StockInsuficienteError) as error:
            _vender(datos_a, [LineaVenta(datos_a.producto.pk, 12)])
        (diferencia,) = error.value.diferencias
        assert (diferencia.stock, diferencia.cantidad, diferencia.unidades) == (10, 12, 2)
        assert diferencia.mensaje == (
            "El sistema tiene 10 unidades de «Bebida Ficticia A» y estás vendiendo 12. "
            "Si continúas, se registra una diferencia de inventario de 2 unidades."
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10
        assert Venta.objects.del_almacen(datos_a.almacen).count() == 1

    def test_con_confirmacion_ajuste_y_salida(self, datos_a):
        venta = _vender(
            datos_a, [LineaVenta(datos_a.producto.pk, 12)], confirmar_diferencias=True
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 0
        ajuste = _movs(datos_a, id_venta=venta, tipo=TipoMovimiento.AJUSTE).get()
        assert (ajuste.cantidad, ajuste.motivo, ajuste.id_usuario) == (
            2,
            MotivoAjuste.VENTA_SIN_STOCK,
            datos_a.vendedor,
        )
        assert _movs(datos_a, id_venta=venta, tipo=TipoMovimiento.SALIDA).get().cantidad == 12

    def test_producto_existente_marcado_como_alta_rapida_sigue_avisando(self, datos_a):
        # Regresión: la alta rápida no apaga el aviso 6a para productos con historial.
        with pytest.raises(StockInsuficienteError):
            _vender(datos_a, [LineaVenta(datos_a.producto.pk, 12, alta_rapida=True)])


@pytest.mark.django_db
class TestAltaRapida2a:
    def test_venta_de_producto_nacido_en_caja(self, datos_a):
        producto = _alta_rapida(datos_a)
        assert producto.id_usuario_creacion == datos_a.vendedor
        assert producto.id_categoria is None
        venta = _vender(datos_a, [LineaVenta(producto.pk, 3, alta_rapida=True)])

        producto.refresh_from_db()
        assert producto.stock_actual == 0
        ajuste = _movs(datos_a, id_venta=venta, tipo=TipoMovimiento.AJUSTE).get()
        salida = _movs(datos_a, id_venta=venta, tipo=TipoMovimiento.SALIDA).get()
        assert (ajuste.cantidad, ajuste.motivo) == (3, MotivoAjuste.ALTA_RAPIDA)
        assert salida.cantidad == 3
        assert ajuste.id_usuario == salida.id_usuario == datos_a.vendedor
        assert venta.total == Decimal("1950")

    def test_venta_abandonada_deja_el_producto_sin_stock_ni_movimientos(self, datos_a):
        # Comportamiento esperado: el alta ocurre fuera de la transacción de la venta.
        producto = _alta_rapida(datos_a)
        assert Producto.objects.del_almacen(datos_a.almacen).filter(pk=producto.pk).exists()
        assert producto.stock_actual == 0
        assert not _movs(datos_a, id_producto=producto).exists()

    def test_alta_rapida_y_producto_sin_stock_en_la_misma_venta(self, datos_a):
        nuevo = _alta_rapida(datos_a)
        with pytest.raises(StockInsuficienteError) as error:
            _vender(
                datos_a,
                [
                    LineaVenta(nuevo.pk, 1, alta_rapida=True),
                    LineaVenta(datos_a.producto.pk, 11),
                ],
            )
        # Sólo se pide confirmar la del producto existente.
        assert [d.id_producto for d in error.value.diferencias] == [datos_a.producto.pk]


@pytest.mark.django_db
class TestIndicadorDeExactitud:
    def test_no_cuenta_alta_rapida_y_si_cuenta_venta_sin_stock(self, datos_a):
        nuevo = _alta_rapida(datos_a)
        _vender(datos_a, [LineaVenta(nuevo.pk, 2, alta_rapida=True)])
        _vender(datos_a, [LineaVenta(datos_a.producto.pk, 12)], confirmar_diferencias=True)
        registrar_ajuste_por_conteo(
            almacen=datos_a.almacen,
            producto=nuevo,
            cantidad_contada=4,
            motivo=MotivoAjuste.DIFERENCIA_INVENTARIO,
            usuario=datos_a.admin,
        )
        motivos = sorted(
            ajustes_de_exactitud(datos_a.almacen).values_list("motivo", flat=True)
        )
        assert motivos == [MotivoAjuste.DIFERENCIA_INVENTARIO, MotivoAjuste.VENTA_SIN_STOCK]

    def test_no_mezcla_almacenes(self, datos_a, datos_b):
        _vender(datos_b, [LineaVenta(datos_b.producto.pk, 12)], confirmar_diferencias=True)
        assert not ajustes_de_exactitud(datos_a.almacen).exists()


@pytest.mark.django_db
class TestAnularVenta:
    def _venta(self, datos, cantidad=3, **cambios):
        return _vender(datos, [LineaVenta(datos.producto.pk, cantidad)], **cambios)

    def _anular(self, datos, venta, **cambios):
        valores = {
            "almacen": datos.almacen,
            "venta": venta,
            "usuario": datos.vendedor,
            "motivo": "El cliente se arrepintió",
        }
        valores.update(cambios)
        return anular_venta(**valores)

    @pytest.mark.parametrize("rol", ["admin", "vendedor"])
    def test_ambos_roles_anulan_y_se_restituye_el_stock(self, datos_a, rol):
        venta = self._venta(datos_a)
        usuario = getattr(datos_a, rol)
        self._anular(datos_a, venta, usuario=usuario)

        venta.refresh_from_db()
        datos_a.producto.refresh_from_db()
        assert venta.estado == EstadoVenta.ANULADA
        assert venta.id_usuario_anulacion == usuario
        assert venta.motivo_anulacion == "El cliente se arrepintió"
        assert venta.fecha_anulacion is not None
        assert datos_a.producto.stock_actual == 10
        entrada = _movs(datos_a, id_venta=venta, tipo=TipoMovimiento.ENTRADA).get()
        assert (entrada.cantidad, entrada.id_usuario, entrada.motivo) == (3, usuario, None)

    def test_la_venta_no_se_borra(self, datos_a):
        venta = self._venta(datos_a)
        self._anular(datos_a, venta)
        assert Venta.objects.del_almacen(datos_a.almacen).filter(pk=venta.pk).exists()
        assert (
            DetalleVenta.objects.del_almacen(datos_a.almacen).filter(id_venta=venta).exists()
        )

    @pytest.mark.parametrize("motivo", ["", "   ", "x", "abcd"])
    def test_motivo_obligatorio(self, datos_a, motivo):
        venta = self._venta(datos_a)
        with pytest.raises(ReglaDeNegocioError, match="motivo"):
            self._anular(datos_a, venta, motivo=motivo)
        venta.refresh_from_db()
        assert venta.estado == EstadoVenta.VIGENTE

    def test_fuera_de_plazo_se_rechaza_e_informa(self, datos_a):
        venta = self._venta(datos_a)
        manana = timezone.localtime(venta.fecha_hora, ZONA_HORARIA_ALMACEN) + timedelta(days=1)
        with pytest.raises(ReglaDeNegocioError, match="el plazo terminó a las 23:59"):
            self._anular(datos_a, venta, momento=manana)
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 7

    def test_no_se_anula_dos_veces(self, datos_a):
        venta = self._venta(datos_a)
        self._anular(datos_a, venta)
        with pytest.raises(ReglaDeNegocioError, match="ya estaba anulada"):
            self._anular(datos_a, venta)
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10

    def test_venta_con_ajuste_6a_anulada(self, datos_a):
        # La diferencia descubierta se mantiene: el almacenero sí tenía esas unidades.
        venta = self._venta(datos_a, cantidad=12, confirmar_diferencias=True)
        self._anular(datos_a, venta)
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 12

    def test_usuario_o_venta_de_otro_almacen(self, datos_a, datos_b):
        venta_b = self._venta(datos_b)
        with pytest.raises(ReglaDeNegocioError):
            self._anular(datos_a, venta_b)
        venta_a = self._venta(datos_a)
        with pytest.raises(ReglaDeNegocioError):
            self._anular(datos_a, venta_a, usuario=datos_b.admin)

    def test_anulacion_dentro_del_plazo_justo_antes_del_limite(self, datos_a):
        venta = self._venta(datos_a)
        dia = timezone.localtime(venta.fecha_hora, ZONA_HORARIA_ALMACEN).date()
        momento = datetime(
            dia.year, dia.month, dia.day, 23, 59, 30, tzinfo=ZONA_HORARIA_ALMACEN
        )
        if momento < venta.fecha_hora:
            pytest.skip("La prueba corre justo en el último minuto del día.")
        self._anular(datos_a, venta, momento=momento)
        venta.refresh_from_db()
        assert venta.estado == EstadoVenta.ANULADA
