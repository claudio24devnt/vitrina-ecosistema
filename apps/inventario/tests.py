from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.inventario.models import Categoria, MovimientoStock, Producto


def _producto(almacen, **campos):
    datos = {"codigo_barras": "7800000000024", "nombre": "Ficticio", "precio": Decimal("500")}
    datos.update(campos)
    return Producto.objects.del_almacen(almacen).create(**datos)


@pytest.mark.django_db
class TestRestriccionesInventario:
    def test_stock_actual_no_puede_ser_negativo(self, almacen):
        with pytest.raises(IntegrityError):
            _producto(almacen, stock_actual=-1)

    def test_tipo_de_movimiento_invalido(self, datos_a):
        # Un tipo inválido viola también ck_movimiento_stock_cantidad; PostgreSQL informa una.
        with pytest.raises(IntegrityError, match="ck_movimiento_stock_(tipo|cantidad)"):
            MovimientoStock.objects.del_almacen(datos_a.almacen).create(
                id_producto=datos_a.producto, id_usuario=datos_a.admin, tipo="robo", cantidad=1
            )

    def test_codigo_de_barras_unico_por_almacen(self, datos_a):
        with pytest.raises(IntegrityError):
            _producto(datos_a.almacen, codigo_barras=datos_a.producto.codigo_barras)

    def test_mismo_codigo_en_dos_almacenes_es_valido(self, datos_a, datos_b):
        # conftest crea el mismo código de barras en A y en B.
        assert datos_a.producto.codigo_barras == datos_b.producto.codigo_barras

    def test_categoria_unica_por_almacen_pero_repetible_entre_almacenes(
        self, datos_a, datos_b
    ):
        assert datos_a.categoria.nombre == datos_b.categoria.nombre
        with pytest.raises(IntegrityError):
            Categoria.objects.del_almacen(datos_a.almacen).create(nombre="Bebidas")

    def test_producto_sin_categoria_es_valido(self, almacen):
        assert _producto(almacen).id_categoria is None

    def test_montos_sin_decimales(self, almacen):
        producto = _producto(almacen, precio=Decimal("1990"))
        producto.refresh_from_db()
        assert producto.precio == Decimal("1990")
        assert producto.precio.as_tuple().exponent == 0

    def test_valores_por_defecto(self, almacen):
        producto = _producto(almacen)
        producto.refresh_from_db()
        assert (producto.stock_actual, producto.stock_minimo) == (0, 0)
        assert producto.fecha_creacion is not None

    def test_producto_con_historial_no_se_puede_borrar(self, datos_a):
        with pytest.raises(ProtectedError), transaction.atomic():
            datos_a.producto.delete()

    def test_stock_bajo(self, almacen):
        en_el_minimo = _producto(almacen, stock_actual=2, stock_minimo=2)
        sobre_el_minimo = _producto(almacen, codigo_barras="2", stock_actual=3, stock_minimo=2)
        assert en_el_minimo.stock_bajo is True
        assert sobre_el_minimo.stock_bajo is False
