import pytest
from django.db.models import ProtectedError
from django.urls import reverse

from apps.inventario.models import Categoria, MovimientoStock, Producto, TipoMovimiento
from apps.inventario.services import (
    crear_producto_con_stock_inicial,
    registrar_entrada_stock,
)
from apps.usuarios.models import Usuario


@pytest.fixture
def categoria(db):
    return Categoria.objects.create(nombre="Bebidas")


@pytest.fixture
def producto(categoria):
    return Producto.objects.create(
        codigo_barras="7801111111111",
        nombre="Agua Mineral 500ml",
        id_categoria=categoria,
        precio="500.00",
        stock_actual=10,
        stock_minimo=5,
    )


@pytest.fixture
def usuario(db):
    return Usuario.objects.create_user(
        email="vendedor@tivoscanea.cl", nombre="Vendedor Uno", password="clave123"
    )


@pytest.mark.django_db
class TestReglasDeNegocioInventario:
    def test_crear_producto_con_stock_inicial_genera_movimiento_entrada(self, categoria):
        producto = crear_producto_con_stock_inicial(
            datos_producto={
                "codigo_barras": "7802222222222",
                "nombre": "Bebida Cola",
                "id_categoria": categoria,
                "precio": "1200.00",
                "stock_minimo": 5,
            },
            stock_inicial=15,
        )

        assert producto.stock_actual == 15
        movimientos = MovimientoStock.objects.filter(id_producto=producto)
        assert movimientos.count() == 1
        assert movimientos.first().tipo == TipoMovimiento.ENTRADA
        assert movimientos.first().cantidad == 15

    def test_crear_producto_sin_stock_inicial_no_genera_movimiento(self, categoria):
        producto = crear_producto_con_stock_inicial(
            datos_producto={
                "codigo_barras": "7803333333333",
                "nombre": "Snack",
                "id_categoria": categoria,
                "precio": "700.00",
                "stock_minimo": 3,
            },
            stock_inicial=0,
        )

        assert producto.stock_actual == 0
        assert MovimientoStock.objects.filter(id_producto=producto).count() == 0

    def test_registrar_entrada_stock_aumenta_stock_y_deja_bitacora(self, producto):
        registrar_entrada_stock(producto=producto, cantidad=5)
        producto.refresh_from_db()

        assert producto.stock_actual == 15
        movimiento = MovimientoStock.objects.get(id_producto=producto)
        assert movimiento.tipo == TipoMovimiento.ENTRADA
        assert movimiento.cantidad == 5

    def test_registrar_entrada_stock_cantidad_invalida_lanza_error(self, producto):
        with pytest.raises(ValueError):
            registrar_entrada_stock(producto=producto, cantidad=0)
        with pytest.raises(ValueError):
            registrar_entrada_stock(producto=producto, cantidad=-3)

    def test_stock_bajo_true_cuando_stock_actual_es_menor_o_igual_al_minimo(self, categoria):
        producto = Producto.objects.create(
            codigo_barras="7804444444444",
            nombre="Fideos",
            id_categoria=categoria,
            precio="900.00",
            stock_actual=3,
            stock_minimo=5,
        )
        assert producto.stock_bajo is True

    def test_stock_bajo_false_cuando_stock_actual_supera_el_minimo(self, producto):
        assert producto.stock_bajo is False

    def test_no_se_puede_duplicar_codigo_de_barras(self, producto, categoria):
        with pytest.raises(Exception):
            Producto.objects.create(
                codigo_barras=producto.codigo_barras,
                nombre="Otro producto",
                id_categoria=categoria,
                precio="100.00",
            )

    def test_no_se_puede_eliminar_producto_con_movimientos(self, producto):
        MovimientoStock.objects.create(
            id_producto=producto, tipo=TipoMovimiento.ENTRADA, cantidad=1
        )
        with pytest.raises(ProtectedError):
            producto.delete()

    def test_no_se_puede_eliminar_categoria_con_productos(self, producto, categoria):
        with pytest.raises(ProtectedError):
            categoria.delete()


@pytest.mark.django_db
class TestVistasInventario:
    def test_lista_productos_requiere_login(self, client):
        respuesta = client.get(reverse("inventario:lista_productos"))
        assert respuesta.status_code == 302
        assert "/cuentas/login/" in respuesta.url

    def test_buscar_por_codigo_encuentra_producto_existente(self, client, usuario, producto):
        client.force_login(usuario)
        respuesta = client.get(
            reverse("inventario:buscar_por_codigo"), {"codigo": producto.codigo_barras}
        )
        datos = respuesta.json()
        assert datos["existe"] is True
        assert datos["producto"]["nombre"] == producto.nombre

    def test_buscar_por_codigo_no_encuentra_producto_inexistente(self, client, usuario):
        client.force_login(usuario)
        respuesta = client.get(
            reverse("inventario:buscar_por_codigo"), {"codigo": "0000000000000"}
        )
        assert respuesta.json() == {"existe": False, "codigo": "0000000000000"}

    def test_crear_producto_por_post_genera_movimiento(self, client, usuario, categoria):
        client.force_login(usuario)
        respuesta = client.post(
            reverse("inventario:crear_producto"),
            {
                "codigo_barras": "7805555555555",
                "nombre": "Yogurt",
                "id_categoria": categoria.id_categoria,
                "precio": "650.00",
                "stock_minimo": 4,
                "stock_inicial": 12,
            },
        )
        assert respuesta.status_code == 302
        producto_creado = Producto.objects.get(codigo_barras="7805555555555")
        assert producto_creado.stock_actual == 12
        assert MovimientoStock.objects.filter(id_producto=producto_creado).count() == 1

    def test_sumar_stock_por_post_aumenta_stock_existente(self, client, usuario, producto):
        client.force_login(usuario)
        stock_previo = producto.stock_actual
        respuesta = client.post(
            reverse("inventario:sumar_stock", args=[producto.id_producto]),
            {"cantidad": 7},
        )
        assert respuesta.status_code == 302
        producto.refresh_from_db()
        assert producto.stock_actual == stock_previo + 7

    def test_eliminar_producto_protegido_muestra_mensaje_y_no_elimina(
        self, client, usuario, producto
    ):
        MovimientoStock.objects.create(
            id_producto=producto, tipo=TipoMovimiento.ENTRADA, cantidad=1
        )
        client.force_login(usuario)
        respuesta = client.post(
            reverse("inventario:eliminar_producto", args=[producto.id_producto])
        )
        assert respuesta.status_code == 302
        assert Producto.objects.filter(pk=producto.pk).exists()

    def test_lista_productos_filtra_por_busqueda(self, client, usuario, producto):
        client.force_login(usuario)
        respuesta = client.get(reverse("inventario:lista_productos"), {"q": "Agua"})
        assert producto in respuesta.context["productos"]

        respuesta_sin_match = client.get(
            reverse("inventario:lista_productos"), {"q": "Inexistente"}
        )
        assert producto not in respuesta_sin_match.context["productos"]

    def test_crear_producto_get_prefiltra_codigo_escaneado(self, client, usuario):
        client.force_login(usuario)
        respuesta = client.get(
            reverse("inventario:crear_producto"), {"codigo": "7809999999999"}
        )
        assert respuesta.status_code == 200
        assert respuesta.context["form"].initial["codigo_barras"] == "7809999999999"

    def test_editar_producto_actualiza_datos_sin_tocar_stock(self, client, usuario, producto):
        client.force_login(usuario)
        respuesta = client.post(
            reverse("inventario:editar_producto", args=[producto.id_producto]),
            {
                "codigo_barras": producto.codigo_barras,
                "nombre": "Agua Mineral 1L",
                "id_categoria": producto.id_categoria_id,
                "precio": "600.00",
                "stock_minimo": producto.stock_minimo,
            },
        )
        assert respuesta.status_code == 302
        producto.refresh_from_db()
        assert producto.nombre == "Agua Mineral 1L"
        assert producto.stock_actual == 10

    def test_escaneo_renderiza_pagina(self, client, usuario):
        client.force_login(usuario)
        respuesta = client.get(reverse("inventario:escaneo"))
        assert respuesta.status_code == 200

    def test_lista_categorias_crea_categoria_por_post(self, client, usuario):
        client.force_login(usuario)
        respuesta = client.post(reverse("inventario:lista_categorias"), {"nombre": "Snacks"})
        assert respuesta.status_code == 302
        assert Categoria.objects.filter(nombre="Snacks").exists()

    def test_eliminar_categoria_sin_productos_se_elimina(self, client, usuario, db):
        categoria_vacia = Categoria.objects.create(nombre="Vacía")
        client.force_login(usuario)
        respuesta = client.post(
            reverse("inventario:eliminar_categoria", args=[categoria_vacia.id_categoria])
        )
        assert respuesta.status_code == 302
        assert not Categoria.objects.filter(pk=categoria_vacia.pk).exists()

    def test_eliminar_categoria_con_productos_protegida(
        self, client, usuario, producto, categoria
    ):
        client.force_login(usuario)
        respuesta = client.post(
            reverse("inventario:eliminar_categoria", args=[categoria.id_categoria])
        )
        assert respuesta.status_code == 302
        assert Categoria.objects.filter(pk=categoria.pk).exists()
