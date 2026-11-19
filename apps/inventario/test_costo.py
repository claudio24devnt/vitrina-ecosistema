"""
Costo del producto (2026-11-19): opcional, sólo para el administrador, y copiado en cada
venta para que la ganancia de períodos pasados no cambie. Todos los datos son FICTICIOS,
creados sólo para pruebas: no provienen del almacén piloto ni de ningún almacén real.
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.almacenes.errores import ReglaDeNegocioError
from apps.inventario.models import Producto
from apps.inventario.servicios import (
    actualizar_producto,
    filtrar_productos,
    registrar_entrada_stock,
    registrar_producto,
    validar_costo,
)
from apps.ventas.models import DetalleVenta, MedioPago
from apps.ventas.servicios import LineaVenta, registrar_venta


def _alta(datos, **cambios):
    valores = {
        "almacen": datos.almacen,
        "usuario": datos.admin,
        "codigo_barras": "7801234500001",
        "nombre": "Galletas Ficticias",
        "precio": Decimal("1000"),
        "stock_inicial": 10,
    }
    valores.update(cambios)
    return registrar_producto(**valores)


def _vender(datos, producto, cantidad=1):
    return registrar_venta(
        almacen=datos.almacen,
        usuario=datos.vendedor,
        lineas=[LineaVenta(producto.pk, cantidad)],
        medio_pago=MedioPago.EFECTIVO,
    )


def _costo_de_la_linea(datos, venta):
    return DetalleVenta.objects.del_almacen(datos.almacen).get(id_venta=venta).costo_unitario


@pytest.mark.django_db
class TestCostoEnElProducto:
    def test_es_opcional_y_vacio_queda_nulo_no_cero(self, datos_a):
        assert _alta(datos_a).costo is None
        assert validar_costo("") is None

    def test_se_guarda_al_registrar(self, datos_a):
        producto = _alta(datos_a, costo=Decimal("650"))
        producto.refresh_from_db()
        assert producto.costo == Decimal("650")

    @pytest.mark.parametrize(
        "costo, mensaje",
        [
            (Decimal("-1"), "no puede ser negativo"),
            (Decimal("10.5"), "sin decimales"),
            (Decimal("99999999999"), "demasiado alto"),
        ],
    )
    def test_rechaza_costos_invalidos_sin_registrar_nada(self, datos_a, costo, mensaje):
        with pytest.raises(ReglaDeNegocioError, match=mensaje):
            _alta(datos_a, costo=costo)
        assert (
            not Producto.objects.del_almacen(datos_a.almacen)
            .filter(codigo_barras="7801234500001")
            .exists()
        )

    def test_puede_ser_mayor_que_el_precio(self, datos_a):
        # Vender bajo el costo (una oferta) es decisión del almacén, no un error.
        assert _alta(datos_a, costo=Decimal("1200")).costo == Decimal("1200")

    def test_la_base_rechaza_un_costo_negativo(self, datos_a):
        with pytest.raises(IntegrityError), transaction.atomic():
            Producto.objects.del_almacen(datos_a.almacen).filter(
                pk=datos_a.producto.pk
            ).update(costo=-1)

    def test_editar_cambia_y_borra_el_costo(self, datos_a):
        producto = _alta(datos_a, costo=Decimal("650"))
        comunes = {
            "almacen": datos_a.almacen,
            "producto": producto,
            "codigo_barras": producto.codigo_barras,
            "nombre": producto.nombre,
            "precio": producto.precio,
            "categoria": None,
            "stock_minimo": 0,
        }
        actualizar_producto(**comunes, costo=Decimal("700"))
        producto.refresh_from_db()
        assert producto.costo == Decimal("700")
        actualizar_producto(**comunes, costo=None)
        producto.refresh_from_db()
        assert producto.costo is None

    def test_sumar_stock_con_costo_nuevo_lo_reemplaza(self, datos_a):
        producto = _alta(datos_a, costo=Decimal("650"))
        registrar_entrada_stock(
            almacen=datos_a.almacen,
            producto=producto,
            cantidad=5,
            usuario=datos_a.admin,
            costo=Decimal("720"),
        )
        producto.refresh_from_db()
        assert (producto.stock_actual, producto.costo) == (15, Decimal("720"))

    def test_sumar_stock_sin_costo_conserva_el_anterior(self, datos_a):
        producto = _alta(datos_a, costo=Decimal("650"))
        registrar_entrada_stock(
            almacen=datos_a.almacen, producto=producto, cantidad=5, usuario=datos_a.admin
        )
        producto.refresh_from_db()
        assert producto.costo == Decimal("650")

    def test_costo_invalido_al_sumar_no_suma_stock(self, datos_a):
        producto = _alta(datos_a)
        with pytest.raises(ReglaDeNegocioError):
            registrar_entrada_stock(
                almacen=datos_a.almacen,
                producto=producto,
                cantidad=5,
                usuario=datos_a.admin,
                costo=Decimal("-5"),
            )
        producto.refresh_from_db()
        assert producto.stock_actual == 10

    def test_filtro_sin_costo(self, datos_a):
        con = _alta(datos_a, costo=Decimal("650"))
        sin = _alta(datos_a, codigo_barras="7801234500002", nombre="Sin costo Ficticio")
        filtrados = set(filtrar_productos(datos_a.almacen, sin_costo=True))
        assert sin in filtrados and datos_a.producto in filtrados
        assert con not in filtrados


@pytest.mark.django_db
class TestCostoEnLaVenta:
    def test_la_venta_copia_el_costo_vigente(self, datos_a):
        producto = _alta(datos_a, costo=Decimal("650"))
        assert _costo_de_la_linea(datos_a, _vender(datos_a, producto)) == Decimal("650")

    def test_cambiar_el_costo_no_toca_las_ventas_ya_hechas(self, datos_a):
        producto = _alta(datos_a, costo=Decimal("650"))
        antes = _vender(datos_a, producto)
        registrar_entrada_stock(
            almacen=datos_a.almacen,
            producto=producto,
            cantidad=5,
            usuario=datos_a.admin,
            costo=Decimal("800"),
        )
        despues = _vender(datos_a, producto)
        assert _costo_de_la_linea(datos_a, antes) == Decimal("650")
        assert _costo_de_la_linea(datos_a, despues) == Decimal("800")

    def test_producto_sin_costo_deja_la_linea_sin_costo(self, datos_a):
        producto = _alta(datos_a)
        assert _costo_de_la_linea(datos_a, _vender(datos_a, producto)) is None

    def test_la_alta_rapida_de_la_caja_nace_sin_costo(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.post(
            reverse("api:alta_rapida"),
            {"codigo_barras": "7809990000011", "nombre": "Rápido Ficticio", "precio": 500},
            content_type="application/json",
        )
        assert respuesta.status_code == 201
        producto = Producto.objects.del_almacen(datos_a.almacen).get(
            codigo_barras="7809990000011"
        )
        assert producto.costo is None


@pytest.mark.django_db
class TestElVendedorNoVeCostos:
    def test_la_busqueda_por_codigo_no_entrega_el_costo_al_vendedor(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            costo=650
        )
        url = reverse("api:producto_por_codigo", args=[datos_a.producto.codigo_barras])
        client.force_login(datos_a.vendedor)
        assert "costo" not in client.get(url).json()["producto"]
        client.force_login(datos_a.admin)
        assert client.get(url).json()["producto"]["costo"] == 650

    def test_el_inventario_del_vendedor_no_muestra_costos(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            costo=654
        )
        client.force_login(datos_a.vendedor)
        html = client.get(
            reverse("inventario:lista_productos") + "?costo=sin"
        ).content.decode()
        assert "Costo" not in html and "$654" not in html
        assert datos_a.producto.nombre in html  # «?costo=sin» no filtra para el vendedor

    def test_el_inventario_del_administrador_muestra_costos(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            costo=654
        )
        client.force_login(datos_a.admin)
        assert "$654" in client.get(reverse("inventario:lista_productos")).content.decode()
        html = client.get(
            reverse("inventario:lista_productos") + "?costo=sin"
        ).content.decode()
        assert "sin costo anotado" in html
        assert datos_a.producto.nombre not in html


@pytest.mark.django_db
class TestPantallasDelCosto:
    def test_alta_con_costo_desde_el_formulario(self, client, datos_a):
        client.force_login(datos_a.admin)
        client.post(
            reverse("inventario:nuevo_producto"),
            {
                "codigo_barras": "7801111222233",
                "nombre": "Té Ficticio",
                "precio": "1490",
                "costo": "990",
                "stock_minimo": "2",
                "stock_inicial": "8",
            },
        )
        producto = Producto.objects.del_almacen(datos_a.almacen).get(
            codigo_barras="7801111222233"
        )
        assert producto.costo == Decimal("990")

    def test_la_edicion_precarga_el_costo(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            costo=650
        )
        client.force_login(datos_a.admin)
        html = client.get(
            reverse("inventario:editar_producto", args=[datos_a.producto.pk])
        ).content.decode()
        assert 'name="costo"' in html and 'value="650"' in html

    def test_sumar_stock_por_api_con_costo(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("api:entrada_stock", args=[datos_a.producto.pk]),
            {"cantidad": 3, "costo": 700},
            content_type="application/json",
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["producto"]["costo"] == 700

    def test_sumar_stock_por_api_con_costo_invalido(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("api:entrada_stock", args=[datos_a.producto.pk]),
            {"cantidad": 3, "costo": -1},
            content_type="application/json",
        )
        assert respuesta.status_code == 400
        assert "El costo va en pesos" in respuesta.json()["detalle"]
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10
