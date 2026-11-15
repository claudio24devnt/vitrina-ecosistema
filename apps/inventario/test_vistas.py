"""Pruebas de integración: vistas, API REST y permisos por rol del módulo de inventario."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento


def _url_codigo(codigo):
    return reverse("api:producto_por_codigo", args=[codigo])


def _url_entrada(producto):
    return reverse("api:entrada_stock", args=[producto.pk])


@pytest.mark.django_db
class TestAccesoPorRol:
    SOLO_ADMIN = [
        "inventario:escanear",
        "inventario:nuevo_producto",
        "inventario:categorias",
        "usuarios:vendedores",
    ]

    @pytest.mark.parametrize("nombre_url", SOLO_ADMIN)
    def test_vendedor_no_entra_a_secciones_de_administrador(self, client, datos_a, nombre_url):
        client.force_login(datos_a.vendedor)
        respuesta = client.get(reverse(nombre_url))
        assert respuesta.status_code == 403
        assert "No tienes permiso" in respuesta.content.decode()

    @pytest.mark.parametrize("nombre_url", SOLO_ADMIN)
    def test_administrador_entra(self, client, datos_a, nombre_url):
        client.force_login(datos_a.admin)
        assert client.get(reverse(nombre_url)).status_code == 200

    def test_vendedor_no_edita_precios(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        url = reverse("inventario:editar_producto", args=[datos_a.producto.pk])
        assert client.get(url).status_code == 403
        client.post(
            url, {"precio": "1", "nombre": "x", "codigo_barras": "1", "stock_minimo": 0}
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.precio == Decimal("1000")

    def test_vendedor_consulta_stock_sin_acciones(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.get(reverse("inventario:lista_productos"))
        assert respuesta.status_code == 200
        assert datos_a.producto.nombre in respuesta.content.decode()
        assert "Editar" not in respuesta.content.decode()

    @pytest.mark.parametrize(
        "nombre_url", ["inicio", "inventario:lista_productos", "inventario:escanear"]
    )
    def test_sin_sesion_redirige_al_login(self, client, nombre_url):
        respuesta = client.get(reverse(nombre_url))
        assert respuesta.status_code == 302
        assert reverse("usuarios:login") in respuesta.url


@pytest.mark.django_db
class TestInventarioPorAlmacen:
    def test_lista_muestra_solo_productos_del_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        contenido = client.get(reverse("inventario:lista_productos")).content.decode()
        assert datos_a.producto.nombre in contenido
        assert datos_b.producto.nombre not in contenido

    def test_no_edita_producto_de_otro_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        url = reverse("inventario:editar_producto", args=[datos_b.producto.pk])
        assert client.get(url).status_code == 404

    def test_formulario_solo_ofrece_categorias_del_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        form = client.get(reverse("inventario:nuevo_producto")).context["form"]
        assert list(form.fields["categoria"].queryset) == [datos_a.categoria]

    def test_filtro_de_stock_bajo(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).create(
            codigo_barras="1",
            nombre="Escaso Ficticio",
            precio=100,
            stock_actual=1,
            stock_minimo=5,
        )
        client.force_login(datos_a.admin)
        respuesta = client.get(reverse("inventario:lista_productos"), {"stock_bajo": "1"})
        nombres = [p.nombre for p in respuesta.context["productos"]]
        assert nombres == ["Escaso Ficticio"]
        assert respuesta.context["total_stock_bajo"] == 1

    def test_busqueda(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.get(reverse("inventario:lista_productos"), {"q": "zzz"})
        assert "No hay productos que coincidan" in respuesta.content.decode()


@pytest.mark.django_db
class TestAltaYEdicion:
    def _datos(self, **cambios):
        datos = {
            "codigo_barras": "7801111222233",
            "nombre": "Té Ficticio",
            "categoria": "",
            "precio": "1490",
            "stock_minimo": "2",
            "stock_inicial": "8",
        }
        datos.update(cambios)
        return datos

    def test_alta_crea_producto_y_movimiento(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(reverse("inventario:nuevo_producto"), self._datos())
        assert respuesta.status_code == 302
        producto = Producto.objects.del_almacen(datos_a.almacen).get(
            codigo_barras="7801111222233"
        )
        assert producto.stock_actual == 8
        assert producto.id_categoria is None
        assert (
            MovimientoStock.objects.del_almacen(datos_a.almacen)
            .filter(id_producto=producto, tipo=TipoMovimiento.ENTRADA, cantidad=8)
            .exists()
        )

    def test_alta_prellena_el_codigo_escaneado(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.get(reverse("inventario:nuevo_producto"), {"codigo": "780555"})
        assert respuesta.context["form"].initial["codigo_barras"] == "780555"

    def test_codigo_duplicado_lleva_a_sumar_stock(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("inventario:nuevo_producto"),
            self._datos(codigo_barras=datos_a.producto.codigo_barras),
            follow=True,
        )
        contenido = respuesta.content.decode()
        assert "ya está registrado en Bebidas" in contenido
        assert respuesta.context["codigo"] == datos_a.producto.codigo_barras
        assert Producto.objects.del_almacen(datos_a.almacen).count() == 1

    def test_alta_con_datos_invalidos_muestra_errores(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(reverse("inventario:nuevo_producto"), self._datos(precio="-5"))
        assert respuesta.status_code == 200
        assert "is-invalid" in respuesta.content.decode()

    def test_editar_no_toca_el_stock_aunque_venga_en_el_formulario(self, client, datos_a):
        client.force_login(datos_a.admin)
        client.post(
            reverse("inventario:editar_producto", args=[datos_a.producto.pk]),
            {
                "codigo_barras": datos_a.producto.codigo_barras,
                "nombre": "Bebida Editada",
                "categoria": datos_a.categoria.pk,
                "precio": "1100",
                "stock_minimo": "3",
                "stock_actual": "999",
            },
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.nombre == "Bebida Editada"
        assert datos_a.producto.precio == Decimal("1100")
        assert datos_a.producto.stock_actual == 10

    def test_categoria_nueva(self, client, datos_a):
        client.force_login(datos_a.admin)
        client.post(reverse("inventario:categorias"), {"nombre": "Lácteos"})
        respuesta = client.post(reverse("inventario:categorias"), {"nombre": "lácteos"})
        assert "Ya existe la categoría" in respuesta.content.decode()
        # Visible: Bootstrap sólo muestra .invalid-feedback junto a un campo is-invalid.
        assert "is-invalid" in respuesta.context["form"].fields["nombre"].widget.attrs["class"]


@pytest.mark.django_db
class TestAPI:
    def test_busca_producto_del_almacen(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.get(_url_codigo(datos_a.producto.codigo_barras))
        assert respuesta.status_code == 200
        producto = respuesta.json()["producto"]
        assert producto["nombre"] == datos_a.producto.nombre
        assert producto["precio"] == 1000
        assert producto["categoria"] == "Bebidas"

    def test_no_encuentra_productos_de_otro_almacen(self, client, datos_a, datos_b):
        Producto.objects.del_almacen(datos_b.almacen).create(
            codigo_barras="SOLO-EN-B", nombre="Ajeno", precio=100
        )
        client.force_login(datos_a.vendedor)
        respuesta = client.get(_url_codigo("SOLO-EN-B"))
        assert respuesta.status_code == 404
        assert respuesta.json() == {"existe": False, "codigo": "SOLO-EN-B"}

    def test_sin_sesion_es_rechazado(self, client, datos_a):
        assert client.get(_url_codigo("x")).status_code == 403

    def test_admin_suma_stock(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            _url_entrada(datos_a.producto), {"cantidad": 7}, content_type="application/json"
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["producto"]["stock_actual"] == 17

    def test_vendedor_no_suma_stock(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.post(
            _url_entrada(datos_a.producto), {"cantidad": 7}, content_type="application/json"
        )
        assert respuesta.status_code == 403
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10

    @pytest.mark.parametrize("cantidad", [0, -1, "abc", None, 100001])
    def test_cantidad_invalida(self, client, datos_a, cantidad):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            _url_entrada(datos_a.producto),
            {"cantidad": cantidad},
            content_type="application/json",
        )
        assert respuesta.status_code == 400
        assert "cantidad" in respuesta.json()["detalle"]

    def test_no_suma_stock_a_producto_de_otro_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            _url_entrada(datos_b.producto), {"cantidad": 1}, content_type="application/json"
        )
        assert respuesta.status_code == 404
        datos_b.producto.refresh_from_db()
        assert datos_b.producto.stock_actual == 10

    def test_post_sin_token_csrf_es_rechazado(self, datos_a):
        from django.test import Client

        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(datos_a.admin)
        respuesta = cliente.post(
            _url_entrada(datos_a.producto), {"cantidad": 1}, content_type="application/json"
        )
        assert respuesta.status_code == 403


@pytest.mark.django_db
class TestPaginas:
    def test_inicio_admin_muestra_accesos_y_cifras(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.get(reverse("inicio"))
        assert respuesta.context["total_productos"] == 1
        assert "Escanear producto" in respuesta.content.decode()

    def test_inicio_vendedor_sin_acciones_de_administrador(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        contenido = client.get(reverse("inicio")).content.decode()
        assert "Escanear producto" not in contenido
        assert "Vendedores" not in contenido

    def test_escanear_con_codigo_en_la_url(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.get(reverse("inventario:escanear"), {"codigo": "123"})
        assert 'value="123"' in respuesta.content.decode()

    def test_login_redirige_al_inicio(self, client, datos_a):
        respuesta = client.post(
            reverse("usuarios:login"),
            {"username": "admin.a@ficticio.test", "password": "clave-de-prueba"},
        )
        assert respuesta.status_code == 302
        assert respuesta.url == reverse("inicio")


@pytest.mark.django_db
class TestInventarioPaginado:
    def _crear(self, almacen, cantidad, prefijo="Producto Ficticio"):
        Producto.objects.del_almacen(almacen).bulk_create(
            [
                Producto(
                    id_almacen=almacen,
                    codigo_barras=f"78100000{i:05d}",
                    nombre=f"{prefijo} {i:03d}",
                    precio=Decimal("500"),
                )
                for i in range(cantidad)
            ]
        )

    def test_pagina_de_a_50_sin_repetir_ni_perder_productos(self, client, datos_a):
        from apps.inventario.views import PRODUCTOS_POR_PAGINA

        self._crear(datos_a.almacen, PRODUCTOS_POR_PAGINA + 10)
        client.force_login(datos_a.admin)
        url = reverse("inventario:lista_productos")
        primera = client.get(url)
        segunda = client.get(url, {"pagina": 2})
        nombres_1 = [p.nombre for p in primera.context["productos"]]
        nombres_2 = [p.nombre for p in segunda.context["productos"]]
        assert len(nombres_1) == PRODUCTOS_POR_PAGINA
        assert len(nombres_2) == 11  # 10 nuevos + la bebida de conftest
        assert not set(nombres_1) & set(nombres_2)
        assert "Siguiente" in primera.content.decode()
        # Una página que no existe muestra la última, sin error.
        assert client.get(url, {"pagina": 99}).context["pagina"].number == 2

    def test_los_enlaces_conservan_la_busqueda(self, client, datos_a):
        from apps.inventario.views import PRODUCTOS_POR_PAGINA

        self._crear(datos_a.almacen, PRODUCTOS_POR_PAGINA + 5)
        client.force_login(datos_a.admin)
        html = client.get(
            reverse("inventario:lista_productos"), {"q": "Ficticio", "pagina": 1}
        ).content.decode()
        assert "?q=Ficticio&amp;pagina=2" in html


def _datos_alta(**cambios):
    datos = {
        "codigo_barras": "7801111222233",
        "nombre": "Té Ficticio",
        "descripcion": "",
        "contenido": "",
        "unidad_contenido": "",
        "categoria": "",
        "categoria_nueva": "",
        "precio": "1490",
        "stock_minimo": "2",
        "stock_inicial": "8",
    }
    datos.update(cambios)
    return datos


@pytest.mark.django_db
class TestFormularioDeProductoMejorado:
    """2026-11-15: descripción, contenido y categoría nueva sin salir del formulario."""

    def _producto(self, almacen):
        return Producto.objects.del_almacen(almacen).get(codigo_barras="7801111222233")

    def test_alta_con_descripcion_contenido_con_coma_y_categoria_nueva(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("inventario:nuevo_producto"),
            _datos_alta(
                descripcion="Hojas de té negro",
                contenido="1,5",
                unidad_contenido="kg",
                categoria_nueva="Infusiones",
            ),
            follow=True,
        )
        assert "Se creó la categoría «Infusiones»" in respuesta.content.decode()
        producto = self._producto(datos_a.almacen)
        assert producto.descripcion == "Hojas de té negro"
        assert producto.contenido_texto == "1,5 kg"
        assert producto.id_categoria.nombre == "Infusiones"
        assert producto.stock_actual == 8

    def test_categoria_nueva_que_ya_existe_usa_la_existente(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("inventario:nuevo_producto"),
            _datos_alta(categoria_nueva="bebidas"),
            follow=True,
        )
        assert "«Bebidas» ya existía y se usó esa" in respuesta.content.decode()
        assert self._producto(datos_a.almacen).id_categoria == datos_a.categoria

    def test_elegir_y_escribir_categoria_muestra_el_error_en_el_campo(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("inventario:nuevo_producto"),
            _datos_alta(categoria=datos_a.categoria.pk, categoria_nueva="Infusiones"),
        )
        assert respuesta.status_code == 200
        form = respuesta.context["form"]
        assert "no las dos a la vez" in form.errors["categoria_nueva"][0]
        assert "is-invalid" in form.fields["categoria_nueva"].widget.attrs["class"]
        assert (
            not Producto.objects.del_almacen(datos_a.almacen)
            .filter(codigo_barras="7801111222233")
            .exists()
        )

    def test_contenido_sin_unidad_marca_la_unidad(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("inventario:nuevo_producto"), _datos_alta(contenido="350")
        )
        assert "unidad_contenido" in respuesta.context["form"].errors

    def test_editar_precarga_y_guarda_los_datos_nuevos(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            descripcion="Retornable", contenido=Decimal("1.50"), unidad_contenido="L"
        )
        client.force_login(datos_a.admin)
        url = reverse("inventario:editar_producto", args=[datos_a.producto.pk])
        inicial = client.get(url).context["form"].initial
        assert (inicial["descripcion"], inicial["contenido"], inicial["unidad_contenido"]) == (
            "Retornable",
            "1,5",
            "L",
        )
        client.post(
            url,
            _datos_alta(
                codigo_barras=datos_a.producto.codigo_barras,
                nombre="Bebida Ficticia A",
                categoria_nueva="Gaseosas",
                contenido="2",
                unidad_contenido="L",
            ),
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.contenido_texto == "2 L"
        assert datos_a.producto.descripcion is None
        assert datos_a.producto.id_categoria.nombre == "Gaseosas"
        assert datos_a.producto.stock_actual == 10

    def test_alta_rapida_de_la_caja_no_pide_descripcion_ni_contenido(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.post(
            reverse("api:alta_rapida"),
            {"codigo_barras": "7809990000011", "nombre": "Nuevo Ficticio", "precio": 500},
            content_type="application/json",
        )
        assert respuesta.status_code == 201
        assert respuesta.json()["producto"]["contenido"] is None
        producto = Producto.objects.del_almacen(datos_a.almacen).get(
            codigo_barras="7809990000011"
        )
        assert (producto.descripcion, producto.contenido, producto.id_categoria) == (
            None,
            None,
            None,
        )


@pytest.mark.django_db
class TestContenidoEnLaCaja:
    def test_la_api_entrega_el_contenido_en_texto(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            contenido=Decimal("350"), unidad_contenido="ml"
        )
        client.force_login(datos_a.vendedor)
        datos = client.get(_url_codigo(datos_a.producto.codigo_barras)).json()
        assert datos["producto"]["contenido"] == "350 ml"

    def test_el_comprobante_muestra_el_contenido(self, client, datos_a):
        Producto.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.producto.pk).update(
            contenido=Decimal("350"), unidad_contenido="ml"
        )
        client.force_login(datos_a.vendedor)
        html = client.get(
            reverse("ventas:comprobante", args=[datos_a.venta.pk])
        ).content.decode()
        assert "Bebida Ficticia A · 350 ml" in html


@pytest.mark.django_db
class TestBusquedaYFiltrosDelInventario:
    @pytest.fixture
    def catalogo(self, datos_a):
        crear = Producto.objects.del_almacen(datos_a.almacen).create
        crear(
            codigo_barras="7803000000014",
            nombre="Detergente Ficticio",
            descripcion="Aroma lavanda",
            contenido=Decimal("3"),
            unidad_contenido="L",
            precio=Decimal("2500"),
            stock_actual=0,
            stock_minimo=1,
        )
        crear(codigo_barras="2900000000024", nombre="Pan Ficticio", precio=Decimal("150"))
        return datos_a

    def _nombres(self, respuesta):
        return [p.nombre for p in respuesta.context["productos"]]

    def test_busca_en_la_descripcion_y_muestra_contenido(self, client, catalogo):
        client.force_login(catalogo.admin)
        respuesta = client.get(reverse("inventario:lista_productos"), {"q": "lavanda"})
        assert self._nombres(respuesta) == ["Detergente Ficticio"]
        html = respuesta.content.decode()
        assert "· 3 L" in html
        assert "Aroma lavanda" in html

    def test_sin_categoria(self, client, catalogo):
        client.force_login(catalogo.admin)
        respuesta = client.get(reverse("inventario:lista_productos"), {"categoria": "sin"})
        assert self._nombres(respuesta) == ["Detergente Ficticio", "Pan Ficticio"]

    def test_por_categoria(self, client, catalogo):
        client.force_login(catalogo.admin)
        respuesta = client.get(
            reverse("inventario:lista_productos"), {"categoria": catalogo.categoria.pk}
        )
        assert self._nombres(respuesta) == ["Bebida Ficticia A"]

    def test_sin_stock_y_orden_por_precio(self, client, catalogo):
        client.force_login(catalogo.admin)
        url = reverse("inventario:lista_productos")
        assert self._nombres(client.get(url, {"stock": "sin"})) == [
            "Detergente Ficticio",
            "Pan Ficticio",
        ]
        assert self._nombres(client.get(url, {"orden": "precio"})) == [
            "Pan Ficticio",
            "Bebida Ficticia A",
            "Detergente Ficticio",
        ]

    def test_stock_bajo_con_el_parametro_nuevo_y_el_antiguo(self, client, catalogo):
        client.force_login(catalogo.admin)
        url = reverse("inventario:lista_productos")
        # Pan Ficticio: stock 0 y mínimo 0 -> en el mínimo, cuenta como stock bajo.
        esperado = ["Detergente Ficticio", "Pan Ficticio"]
        assert self._nombres(client.get(url, {"stock": "bajo"})) == esperado
        assert self._nombres(client.get(url, {"stock_bajo": "1"})) == esperado

    def test_valores_raros_en_la_url_se_ignoran(self, client, catalogo, datos_b):
        client.force_login(catalogo.admin)
        respuesta = client.get(
            reverse("inventario:lista_productos"),
            {"categoria": datos_b.categoria.pk, "stock": "x", "orden": "nada"},
        )
        assert respuesta.status_code == 200
        assert len(self._nombres(respuesta)) == 3
        assert "is-invalid" not in respuesta.content.decode()

    def test_sin_resultados_ofrece_limpiar_filtros(self, client, catalogo):
        client.force_login(catalogo.admin)
        html = client.get(
            reverse("inventario:lista_productos"), {"q": "zzz", "stock": "sin"}
        ).content.decode()
        assert "No hay productos que coincidan con la búsqueda o los filtros" in html
        assert "Limpiar filtros" in html

    def test_la_paginacion_conserva_filtros_y_orden(self, client, catalogo):
        from apps.inventario.views import PRODUCTOS_POR_PAGINA

        Producto.objects.del_almacen(catalogo.almacen).bulk_create(
            [
                Producto(
                    id_almacen=catalogo.almacen,
                    codigo_barras=f"78200000{i:05d}",
                    nombre=f"Fideo Ficticio {i:03d}",
                    precio=Decimal("900"),
                )
                for i in range(PRODUCTOS_POR_PAGINA + 1)
            ]
        )
        client.force_login(catalogo.admin)
        html = client.get(
            reverse("inventario:lista_productos"),
            {"q": "fideo", "categoria": "sin", "stock": "sin", "orden": "precio"},
        ).content.decode()
        assert "?q=fideo&amp;categoria=sin&amp;stock=sin&amp;orden=precio&amp;pagina=2" in html

    def test_el_vendedor_tambien_busca_y_filtra(self, client, catalogo):
        client.force_login(catalogo.vendedor)
        respuesta = client.get(
            reverse("inventario:lista_productos"), {"q": "detergente", "stock": "sin"}
        )
        assert self._nombres(respuesta) == ["Detergente Ficticio"]
        assert "Editar" not in respuesta.content.decode()

    def test_no_muestra_productos_de_otro_almacen(self, client, catalogo, datos_b):
        client.force_login(catalogo.admin)
        respuesta = client.get(reverse("inventario:lista_productos"), {"q": "ficticia"})
        assert "Bebida Ficticia B" not in self._nombres(respuesta)
        opciones = dict(respuesta.context["filtro"].fields["categoria"].choices)
        assert str(datos_b.categoria.pk) not in opciones
