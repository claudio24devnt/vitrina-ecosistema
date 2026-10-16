"""
1.4.3 — Autor del producto y del movimiento, motivo del ajuste.
Las restricciones las rechaza la base de datos; la coherencia de almacén, el servicio.
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.almacenes.errores import ReglaDeNegocioError
from apps.inventario.models import (
    MOTIVOS_AJUSTE_MANUAL,
    MotivoAjuste,
    MovimientoStock,
    TipoMovimiento,
)
from apps.inventario.servicios import (
    registrar_ajuste_por_conteo,
    registrar_movimiento,
    registrar_producto,
)


def _crear(datos, **campos):
    """INSERT directo (sin servicio) para que la que decida sea la base de datos."""
    valores = {"id_producto": datos.producto, "id_usuario": datos.admin}
    valores.update(campos)
    return MovimientoStock.objects.del_almacen(datos.almacen).create(**valores)


@pytest.mark.django_db
class TestRestriccionCantidadEnDosSentidos:
    @pytest.mark.parametrize(
        "campos",
        [
            {"tipo": TipoMovimiento.SALIDA, "cantidad": -1},
            {"tipo": TipoMovimiento.ENTRADA, "cantidad": 0},
            {
                "tipo": TipoMovimiento.AJUSTE,
                "cantidad": 0,
                "motivo": MotivoAjuste.PRODUCTO_DANADO,
            },
            {"tipo": TipoMovimiento.AJUSTE, "cantidad": -2},
            {
                "tipo": TipoMovimiento.SALIDA,
                "cantidad": 1,
                "motivo": MotivoAjuste.PRODUCTO_DANADO,
            },
        ],
        ids=[
            "salida_negativa",
            "entrada_cero",
            "ajuste_cero",
            "ajuste_sin_motivo",
            "salida_con_motivo",
        ],
    )
    def test_rechazado_por_la_base(self, datos_a, campos):
        with pytest.raises(IntegrityError, match="ck_movimiento_stock_cantidad"):
            _crear(datos_a, **campos)

    @pytest.mark.parametrize(
        "campos",
        [
            {"tipo": TipoMovimiento.ENTRADA, "cantidad": 3},
            {"tipo": TipoMovimiento.SALIDA, "cantidad": 3},
            {
                "tipo": TipoMovimiento.AJUSTE,
                "cantidad": -2,
                "motivo": MotivoAjuste.PRODUCTO_VENCIDO,
            },
            {"tipo": TipoMovimiento.AJUSTE, "cantidad": 5, "motivo": MotivoAjuste.ALTA_RAPIDA},
        ],
    )
    def test_combinaciones_validas(self, datos_a, campos):
        assert _crear(datos_a, **campos).pk


@pytest.mark.django_db
class TestMotivoYUsuario:
    def test_motivo_fuera_de_la_lista_es_rechazado_por_la_base(self, datos_a):
        with pytest.raises(IntegrityError, match="ck_movimiento_stock_motivo"):
            _crear(
                datos_a, tipo=TipoMovimiento.AJUSTE, cantidad=-1, motivo="Se lo comió el gato"
            )

    def test_movimiento_sin_usuario_falla(self, datos_a):
        with pytest.raises(IntegrityError, match="id_usuario"):
            _crear(datos_a, id_usuario=None, tipo=TipoMovimiento.ENTRADA, cantidad=1)


@pytest.mark.django_db
class TestCoherenciaDeAlmacenDelUsuario:
    def test_movimiento_con_usuario_de_otro_almacen_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            registrar_movimiento(
                producto=datos_a.producto,
                tipo=TipoMovimiento.ENTRADA,
                cantidad=1,
                usuario=datos_b.admin,
            )

    def test_producto_creado_por_usuario_de_otro_almacen_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            registrar_producto(
                almacen=datos_a.almacen,
                usuario=datos_b.admin,
                codigo_barras="7800000000099",
                nombre="Ficticio",
                precio=Decimal("100"),
            )

    def test_el_alta_graba_el_autor(self, datos_a):
        producto = registrar_producto(
            almacen=datos_a.almacen,
            usuario=datos_a.vendedor,
            codigo_barras="7800000000098",
            nombre="Ficticio",
            precio=Decimal("100"),
            stock_inicial=4,
        )
        assert producto.id_usuario_creacion == datos_a.vendedor
        entrada = MovimientoStock.objects.del_almacen(datos_a.almacen).get(
            id_producto=producto
        )
        assert entrada.id_usuario == datos_a.vendedor


@pytest.mark.django_db
class TestAjustePorConteo:
    def _ajustar(self, datos, contada, motivo=MotivoAjuste.DIFERENCIA_INVENTARIO, **cambios):
        valores = {
            "almacen": datos.almacen,
            "producto": datos.producto,
            "cantidad_contada": contada,
            "motivo": motivo,
            "usuario": datos.admin,
        }
        valores.update(cambios)
        return registrar_ajuste_por_conteo(**valores)

    def test_conteo_menor_deja_ajuste_negativo(self, datos_a):
        movimiento = self._ajustar(datos_a, 8, MotivoAjuste.PRODUCTO_DANADO)
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 8
        assert (movimiento.tipo, movimiento.cantidad, movimiento.motivo) == (
            TipoMovimiento.AJUSTE,
            -2,
            MotivoAjuste.PRODUCTO_DANADO,
        )
        assert movimiento.id_usuario == datos_a.admin

    def test_conteo_mayor_deja_ajuste_positivo(self, datos_a):
        assert self._ajustar(datos_a, 15).cantidad == 5

    def test_conteo_igual_no_genera_movimiento(self, datos_a):
        with pytest.raises(ReglaDeNegocioError, match="No hay diferencia"):
            self._ajustar(datos_a, 10)

    def test_conteo_cero_es_valido(self, datos_a):
        assert self._ajustar(datos_a, 0, MotivoAjuste.PRODUCTO_VENCIDO).cantidad == -10

    def test_conteo_negativo_es_rechazado(self, datos_a):
        with pytest.raises(ReglaDeNegocioError):
            self._ajustar(datos_a, -1)

    @pytest.mark.parametrize(
        "motivo", [MotivoAjuste.VENTA_SIN_STOCK, MotivoAjuste.ALTA_RAPIDA]
    )
    def test_motivos_de_la_caja_no_se_eligen_a_mano(self, datos_a, motivo):
        with pytest.raises(ReglaDeNegocioError):
            self._ajustar(datos_a, 12, motivo)

    def test_lista_manual_tiene_los_cuatro_motivos(self):
        assert len(MOTIVOS_AJUSTE_MANUAL) == 4
        assert MotivoAjuste.ALTA_RAPIDA not in MOTIVOS_AJUSTE_MANUAL
        assert MotivoAjuste.VENTA_SIN_STOCK not in MOTIVOS_AJUSTE_MANUAL

    def test_usuario_de_otro_almacen_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            self._ajustar(datos_a, 8, usuario=datos_b.admin)
