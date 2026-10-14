"""Pruebas unitarias de la capa de servicios de inventario (CU-01)."""

from decimal import Decimal

import pytest
from conftest import usuario_de

from apps.almacenes.errores import ReglaDeNegocioError
from apps.inventario import servicios
from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento
from apps.inventario.servicios import (
    CodigoDuplicadoError,
    actualizar_producto,
    buscar_por_codigo,
    crear_categoria,
    registrar_entrada_stock,
    registrar_producto,
)


def _registrar(almacen, **cambios):
    datos = {
        "almacen": almacen,
        "usuario": cambios.pop("usuario", None) or usuario_de(almacen),
        "codigo_barras": "7801234567890",
        "nombre": "Galletas Ficticias",
        "precio": Decimal("890"),
        "stock_minimo": 3,
        "stock_inicial": 12,
    }
    datos.update(cambios)
    return registrar_producto(**datos)


def _movimientos(producto):
    return MovimientoStock.objects.del_almacen(producto.id_almacen_id).filter(
        id_producto=producto
    )


@pytest.mark.django_db
class TestRegistrarProducto:
    def test_con_stock_inicial_genera_movimiento_de_entrada(self, almacen):
        producto = _registrar(almacen)
        assert producto.stock_actual == 12
        (movimiento,) = _movimientos(producto)
        assert (movimiento.tipo, movimiento.cantidad) == (TipoMovimiento.ENTRADA, 12)
        assert movimiento.id_almacen_id == almacen.pk

    def test_sin_stock_inicial_no_genera_movimiento(self, almacen):
        producto = _registrar(almacen, stock_inicial=0)
        assert producto.stock_actual == 0
        assert not _movimientos(producto).exists()

    def test_codigo_existente_no_duplica_y_ofrece_el_existente(self, datos_a):
        with pytest.raises(CodigoDuplicadoError) as error:
            _registrar(datos_a.almacen, codigo_barras=datos_a.producto.codigo_barras)
        assert error.value.producto == datos_a.producto
        assert "ya está registrado en Bebidas" in str(error.value)
        assert Producto.objects.del_almacen(datos_a.almacen).count() == 1

    def test_codigo_con_espacios_se_reconoce_como_existente(self, datos_a):
        with pytest.raises(CodigoDuplicadoError):
            _registrar(datos_a.almacen, codigo_barras=f"  {datos_a.producto.codigo_barras} ")

    def test_mismo_codigo_en_otro_almacen_se_registra(self, datos_a, datos_b, almacen):
        producto = _registrar(almacen, codigo_barras=datos_a.producto.codigo_barras)
        assert producto.id_almacen_id == almacen.pk

    def test_categoria_de_otro_almacen_es_rechazada(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            _registrar(datos_a.almacen, categoria=datos_b.categoria)

    def test_stock_inicial_negativo_es_rechazado(self, almacen):
        with pytest.raises(ReglaDeNegocioError):
            _registrar(almacen, stock_inicial=-1)

    def test_si_falla_el_movimiento_no_queda_el_producto(self, almacen, monkeypatch):
        def falla(**kwargs):
            raise RuntimeError("falla forzada")

        monkeypatch.setattr(servicios, "registrar_movimiento", falla)
        with pytest.raises(RuntimeError):
            _registrar(almacen)
        assert not Producto.objects.del_almacen(almacen).exists()


@pytest.mark.django_db
class TestEntradaDeStock:
    def test_suma_stock_y_deja_movimiento(self, datos_a):
        registrar_entrada_stock(
            almacen=datos_a.almacen,
            producto=datos_a.producto,
            cantidad=5,
            usuario=datos_a.admin,
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 15
        entrada = _movimientos(datos_a.producto).get(tipo=TipoMovimiento.ENTRADA)
        assert entrada.cantidad == 5
        assert entrada.id_almacen_id == datos_a.almacen.pk

    @pytest.mark.parametrize("cantidad", [0, -3, None])
    def test_cantidad_invalida_es_rechazada(self, datos_a, cantidad):
        with pytest.raises(ReglaDeNegocioError):
            registrar_entrada_stock(
                almacen=datos_a.almacen,
                producto=datos_a.producto,
                cantidad=cantidad,
                usuario=datos_a.admin,
            )

    def test_producto_de_otro_almacen_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            registrar_entrada_stock(
                almacen=datos_a.almacen,
                producto=datos_b.producto,
                cantidad=1,
                usuario=datos_a.admin,
            )
        datos_b.producto.refresh_from_db()
        assert datos_b.producto.stock_actual == 10

    def test_si_falla_el_movimiento_no_cambia_el_stock(self, datos_a, monkeypatch):
        def falla(**kwargs):
            raise RuntimeError("falla forzada")

        monkeypatch.setattr(servicios, "registrar_movimiento", falla)
        with pytest.raises(RuntimeError):
            registrar_entrada_stock(
                almacen=datos_a.almacen,
                producto=datos_a.producto,
                cantidad=5,
                usuario=datos_a.admin,
            )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10


@pytest.mark.django_db
class TestCoherenciaDeAlmacen:
    def test_movimiento_ligado_a_venta_de_otro_almacen_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            servicios.registrar_movimiento(
                producto=datos_a.producto,
                tipo=TipoMovimiento.SALIDA,
                cantidad=1,
                venta=datos_b.venta,
                usuario=datos_a.admin,
            )

    def test_movimiento_toma_el_almacen_del_producto(self, datos_a):
        movimiento = servicios.registrar_movimiento(
            producto=datos_a.producto,
            tipo=TipoMovimiento.AJUSTE,
            cantidad=1,
            motivo="Producto dañado",
            usuario=datos_a.admin,
        )
        assert movimiento.id_almacen_id == datos_a.producto.id_almacen_id


@pytest.mark.django_db
class TestActualizarProducto:
    def _actualizar(self, datos, **cambios):
        valores = {
            "almacen": datos.almacen,
            "producto": datos.producto,
            "codigo_barras": datos.producto.codigo_barras,
            "nombre": "Bebida Renombrada",
            "precio": Decimal("1290"),
            "categoria": datos.categoria,
            "stock_minimo": 4,
        }
        valores.update(cambios)
        return actualizar_producto(**valores)

    def test_cambia_datos_sin_tocar_stock(self, datos_a):
        self._actualizar(datos_a)
        datos_a.producto.refresh_from_db()
        assert (datos_a.producto.nombre, datos_a.producto.precio) == (
            "Bebida Renombrada",
            Decimal("1290"),
        )
        assert datos_a.producto.stock_actual == 10

    def test_no_puede_tomar_el_codigo_de_otro_producto(self, datos_a):
        otro = _registrar(datos_a.almacen, codigo_barras="7809999999999", stock_inicial=0)
        with pytest.raises(CodigoDuplicadoError):
            self._actualizar(datos_a, codigo_barras=otro.codigo_barras)

    def test_producto_de_otro_almacen_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            self._actualizar(datos_a, producto=datos_b.producto, categoria=None)


@pytest.mark.django_db
class TestBusquedaYCategorias:
    def test_buscar_solo_en_el_almacen(self, datos_a, datos_b):
        assert buscar_por_codigo(datos_a.almacen, datos_a.producto.codigo_barras) == (
            datos_a.producto
        )
        assert buscar_por_codigo(datos_a.almacen, "") is None
        assert buscar_por_codigo(datos_a.almacen, "no-existe") is None

    def test_categoria_duplicada_sin_importar_mayusculas(self, datos_a):
        with pytest.raises(ReglaDeNegocioError, match="Ya existe"):
            crear_categoria(almacen=datos_a.almacen, nombre="  bebidas ")

    def test_categoria_vacia(self, almacen):
        with pytest.raises(ReglaDeNegocioError):
            crear_categoria(almacen=almacen, nombre="   ")

    def test_crea_categoria(self, almacen):
        assert crear_categoria(almacen=almacen, nombre="Lácteos").nombre == "Lácteos"
