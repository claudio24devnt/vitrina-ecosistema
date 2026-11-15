"""Pruebas unitarias de la capa de servicios de inventario (CU-01)."""

from decimal import Decimal

import pytest
from conftest import usuario_de

from apps.almacenes.errores import ReglaDeNegocioError
from apps.inventario import servicios
from apps.inventario.models import Categoria, MovimientoStock, Producto, TipoMovimiento
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


@pytest.mark.django_db
class TestDescripcionYContenidoEnServicios:
    def test_alta_guarda_descripcion_y_contenido(self, almacen):
        producto = _registrar(
            almacen,
            descripcion="  Sabor frutilla, sin azúcar  ",
            contenido=Decimal("1.5"),
            unidad_contenido="L",
        )
        producto.refresh_from_db()
        assert producto.descripcion == "Sabor frutilla, sin azúcar"
        assert producto.contenido_texto == "1,5 L"

    def test_textos_vacios_quedan_null(self, almacen):
        producto = _registrar(almacen, descripcion="   ", unidad_contenido="")
        producto.refresh_from_db()
        assert (producto.descripcion, producto.contenido, producto.unidad_contenido) == (
            None,
            None,
            None,
        )

    @pytest.mark.parametrize(
        "campos, mensaje",
        [
            ({"contenido": Decimal("350")}, "elige la unidad"),
            ({"unidad_contenido": "ml"}, "elige la unidad"),
            ({"contenido": Decimal("0"), "unidad_contenido": "ml"}, "mayor que cero"),
            ({"contenido": Decimal("1.555"), "unidad_contenido": "kg"}, "dos decimales"),
            ({"contenido": Decimal("350"), "unidad_contenido": "cc"}, "unidad de la lista"),
            ({"descripcion": "x" * 301}, "300 caracteres"),
        ],
    )
    def test_datos_descriptivos_invalidos_no_registran_nada(self, almacen, campos, mensaje):
        with pytest.raises(ReglaDeNegocioError, match=mensaje):
            _registrar(almacen, **campos)
        assert not Producto.objects.del_almacen(almacen).exists()

    def test_editar_cambia_y_borra_los_datos_descriptivos(self, datos_a):
        datos = {
            "almacen": datos_a.almacen,
            "producto": datos_a.producto,
            "codigo_barras": datos_a.producto.codigo_barras,
            "nombre": datos_a.producto.nombre,
            "precio": datos_a.producto.precio,
            "categoria": datos_a.categoria,
            "stock_minimo": 2,
        }
        actualizar_producto(
            **datos, descripcion="Retornable", contenido=Decimal("2"), unidad_contenido="L"
        )
        datos_a.producto.refresh_from_db()
        assert (datos_a.producto.descripcion, datos_a.producto.contenido_texto) == (
            "Retornable",
            "2 L",
        )
        actualizar_producto(**datos)
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.descripcion is None
        assert datos_a.producto.contenido is None
        assert datos_a.producto.stock_actual == 10


def _categorias(almacen):
    return list(Categoria.objects.del_almacen(almacen).values_list("nombre", flat=True))


@pytest.mark.django_db
class TestCategoriaNuevaEnElFormulario:
    def test_alta_crea_la_categoria_y_la_asigna(self, almacen):
        producto = _registrar(almacen, categoria_nueva="  Aseo   y limpieza ")
        assert producto.id_categoria.nombre == "Aseo y limpieza"
        assert producto.categoria_creada is True
        assert producto.id_categoria.id_almacen_id == almacen.pk

    def test_si_ya_existe_usa_la_existente(self, datos_a):
        producto = _registrar(datos_a.almacen, categoria_nueva="  BEBIDAS ")
        assert producto.id_categoria == datos_a.categoria
        assert producto.categoria_creada is False
        assert _categorias(datos_a.almacen) == ["Bebidas"]

    def test_la_categoria_de_otro_almacen_no_cuenta_como_existente(self, datos_a, datos_b):
        Categoria.objects.del_almacen(datos_b.almacen).create(nombre="Lácteos")
        producto = _registrar(datos_a.almacen, codigo_barras="7802", categoria_nueva="Lácteos")
        assert producto.categoria_creada is True
        assert producto.id_categoria.id_almacen_id == datos_a.almacen.pk
        assert sorted(_categorias(datos_b.almacen)) == ["Bebidas", "Lácteos"]

    def test_elegir_y_escribir_a_la_vez_es_rechazado(self, datos_a):
        with pytest.raises(ReglaDeNegocioError, match="no las dos a la vez"):
            _registrar(datos_a.almacen, categoria=datos_a.categoria, categoria_nueva="Aseo")
        assert _categorias(datos_a.almacen) == ["Bebidas"]

    def test_si_falla_el_alta_la_categoria_no_queda(self, almacen, monkeypatch):
        def falla(**kwargs):
            raise RuntimeError("falla forzada")

        monkeypatch.setattr(servicios, "registrar_movimiento", falla)
        with pytest.raises(RuntimeError):
            _registrar(almacen, categoria_nueva="Congelados")
        assert not Producto.objects.del_almacen(almacen).exists()
        assert _categorias(almacen) == []

    def test_codigo_duplicado_no_crea_la_categoria(self, datos_a):
        with pytest.raises(CodigoDuplicadoError):
            _registrar(
                datos_a.almacen,
                codigo_barras=datos_a.producto.codigo_barras,
                categoria_nueva="Congelados",
            )
        assert _categorias(datos_a.almacen) == ["Bebidas"]

    def test_categoria_creada_en_paralelo_se_reutiliza(self, almacen, monkeypatch):
        """Otro usuario la crea entre la búsqueda y el INSERT: se usa la suya."""
        otra = Categoria.objects.del_almacen(almacen).create(nombre="Panadería")
        busquedas = iter([None, otra])
        monkeypatch.setattr(servicios, "buscar_categoria", lambda *a: next(busquedas))
        monkeypatch.setattr(
            servicios,
            "crear_categoria",
            lambda **kw: Categoria.objects.del_almacen(almacen).create(nombre="Panadería"),
        )
        categoria, creada = servicios.obtener_o_crear_categoria(
            almacen=almacen, nombre="panadería"
        )
        assert (categoria, creada) == (otra, False)

    def test_editar_con_categoria_nueva(self, datos_a):
        producto = actualizar_producto(
            almacen=datos_a.almacen,
            producto=datos_a.producto,
            codigo_barras=datos_a.producto.codigo_barras,
            nombre=datos_a.producto.nombre,
            precio=datos_a.producto.precio,
            categoria=None,
            categoria_nueva="Gaseosas",
            stock_minimo=2,
        )
        producto.refresh_from_db()
        assert producto.id_categoria.nombre == "Gaseosas"

    def test_editar_si_falla_no_crea_la_categoria(self, datos_a):
        otro = _registrar(datos_a.almacen, codigo_barras="7809999999999", stock_inicial=0)
        with pytest.raises(CodigoDuplicadoError):
            actualizar_producto(
                almacen=datos_a.almacen,
                producto=datos_a.producto,
                codigo_barras=otro.codigo_barras,
                nombre="X",
                precio=Decimal("1"),
                categoria=None,
                categoria_nueva="Gaseosas",
                stock_minimo=0,
            )
        assert _categorias(datos_a.almacen) == ["Bebidas"]

    def test_crear_categoria_normaliza_espacios(self, datos_a):
        with pytest.raises(ReglaDeNegocioError, match="Ya existe"):
            crear_categoria(almacen=datos_a.almacen, nombre=" bebidas ")
        assert crear_categoria(almacen=datos_a.almacen, nombre="Pan   amasado").nombre == (
            "Pan amasado"
        )


@pytest.mark.django_db
class TestFiltrarProductos:
    @pytest.fixture
    def catalogo(self, datos_a):
        almacen = datos_a.almacen
        aseo = Categoria.objects.del_almacen(almacen).create(nombre="Aseo")
        crear = Producto.objects.del_almacen(almacen).create
        crear(
            codigo_barras="7802000000011",
            nombre="Detergente Ficticio",
            descripcion="Aroma lavanda",
            precio=Decimal("2500"),
            stock_actual=0,
            stock_minimo=1,
            id_categoria=aseo,
        )
        crear(
            codigo_barras="7802000000028",
            nombre="Jabón Ficticio",
            precio=Decimal("700"),
            stock_actual=3,
            stock_minimo=5,
            id_categoria=aseo,
        )
        crear(
            codigo_barras="2900000000017",
            nombre="Alta Rápida Ficticia",
            precio=Decimal("300"),
            stock_actual=20,
        )
        # El producto de conftest: «Bebida Ficticia A», Bebidas, stock 10, mínimo 2, $1000.
        return datos_a

    def _nombres(self, almacen, **criterios):
        return [p.nombre for p in servicios.filtrar_productos(almacen, **criterios)]

    def test_sin_filtros_trae_todo_ordenado_por_nombre(self, catalogo):
        assert self._nombres(catalogo.almacen) == [
            "Alta Rápida Ficticia",
            "Bebida Ficticia A",
            "Detergente Ficticio",
            "Jabón Ficticio",
        ]

    @pytest.mark.parametrize(
        "texto, esperado",
        [
            ("jabón", ["Jabón Ficticio"]),  # nombre, sin distinguir mayúsculas
            ("78020000000", ["Detergente Ficticio", "Jabón Ficticio"]),  # código parcial
            ("LAVANDA", ["Detergente Ficticio"]),  # descripción
            ("ficticio aroma", ["Detergente Ficticio"]),  # cada palabra en cualquier campo
            ("ficticio zzz", []),
        ],
    )
    def test_busqueda_por_texto(self, catalogo, texto, esperado):
        assert self._nombres(catalogo.almacen, texto=texto) == esperado

    def test_por_categoria_y_sin_categoria(self, catalogo):
        aseo = Categoria.objects.del_almacen(catalogo.almacen).get(nombre="Aseo")
        assert self._nombres(catalogo.almacen, categoria=aseo) == [
            "Detergente Ficticio",
            "Jabón Ficticio",
        ]
        assert self._nombres(catalogo.almacen, categoria=servicios.SIN_CATEGORIA) == [
            "Alta Rápida Ficticia"
        ]

    def test_stock_bajo_usa_la_misma_regla_que_la_alerta(self, catalogo):
        bajo = self._nombres(catalogo.almacen, stock="bajo")
        assert bajo == ["Detergente Ficticio", "Jabón Ficticio"]
        assert set(bajo) == {
            p.nombre for p in servicios.productos_con_stock_bajo(catalogo.almacen)
        }

    def test_sin_stock(self, catalogo):
        assert self._nombres(catalogo.almacen, stock="sin") == ["Detergente Ficticio"]

    def test_ordenes(self, catalogo):
        assert self._nombres(catalogo.almacen, orden="stock")[0] == "Detergente Ficticio"
        assert self._nombres(catalogo.almacen, orden="precio") == [
            "Alta Rápida Ficticia",
            "Jabón Ficticio",
            "Bebida Ficticia A",
            "Detergente Ficticio",
        ]
        # Un orden desconocido vuelve al de nombre.
        assert self._nombres(catalogo.almacen, orden="-stock_actual") == self._nombres(
            catalogo.almacen
        )

    def test_filtros_combinados(self, catalogo):
        aseo = Categoria.objects.del_almacen(catalogo.almacen).get(nombre="Aseo")
        assert self._nombres(
            catalogo.almacen, texto="ficticio", categoria=aseo, stock="sin"
        ) == ["Detergente Ficticio"]

    def test_solo_productos_del_almacen(self, catalogo, datos_b):
        assert self._nombres(datos_b.almacen, texto="ficticia") == ["Bebida Ficticia B"]
        assert "Bebida Ficticia B" not in self._nombres(catalogo.almacen, texto="bebida")
        assert self._nombres(datos_b.almacen, categoria=servicios.SIN_CATEGORIA) == []

    def test_categoria_de_otro_almacen_es_rechazada(self, catalogo, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            servicios.filtrar_productos(catalogo.almacen, categoria=datos_b.categoria)
