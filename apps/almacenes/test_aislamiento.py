"""
Aislamiento multi-almacén sobre las diez tablas: ningún almacén puede leer,
contar, modificar ni borrar datos de otro, y una consulta sin del_almacen() falla.
"""

from datetime import date

import pytest
from django.db.models import Count

from apps.almacenes.aislamiento import ConsultaSinAlmacenError
from apps.almacenes.models import Almacen, FranjaHoraria
from apps.inventario.models import Categoria, MovimientoStock, Producto
from apps.reporteria.models import AccesoReporte, Alerta
from apps.usuarios.models import Usuario
from apps.ventas.models import DetalleVenta, Venta

# modelo -> (cómo obtener un registro propio desde DatosAlmacen, campo y valor inocuo)
TABLAS = {
    Almacen: (lambda d: d.almacen, "plan", "otro"),
    Usuario: (lambda d: d.vendedor, "nombre", "Modificado"),
    Categoria: (lambda d: d.categoria, "nombre", "Modificada"),
    Producto: (lambda d: d.producto, "nombre", "Modificado"),
    Venta: (lambda d: d.venta, "medio_pago", "debito"),
    DetalleVenta: (lambda d: d.detalle, "cantidad", 99),
    MovimientoStock: (lambda d: d.movimiento, "cantidad", 99),
    AccesoReporte: (lambda d: d.acceso, "mes_consultado", date(2026, 1, 1)),
    Alerta: (lambda d: d.alerta, "mensaje", "Modificada"),
    FranjaHoraria: (
        lambda d: FranjaHoraria.sin_aislamiento.filter(id_almacen=d.almacen).first(),
        "nombre",
        "Modificada",
    ),
}

parametrizar_tablas = pytest.mark.parametrize(
    "modelo", list(TABLAS), ids=[m._meta.db_table for m in TABLAS]
)


def test_cubre_las_diez_tablas():
    assert sorted(m._meta.db_table for m in TABLAS) == sorted(
        [
            "almacen",
            "usuario",
            "categoria",
            "producto",
            "venta",
            "detalle_venta",
            "movimiento_stock",
            "acceso_reporte",
            "franja_horaria",
            "alerta",
        ]
    )


@pytest.mark.django_db
class TestConsultaSinAlmacenFalla:
    OPERACIONES = {
        "listar": lambda qs: list(qs.all()),
        "iterar": lambda qs: [x for x in qs.filter(pk__gt=0)],
        "contar": lambda qs: qs.count(),
        "existe": lambda qs: qs.exists(),
        "agregar": lambda qs: qs.aggregate(n=Count("pk")),
        "primero": lambda qs: qs.first(),
        "obtener": lambda qs: qs.get(pk=1),
        "valores": lambda qs: list(qs.values_list("pk", flat=True)),
        "iterator": lambda qs: list(qs.iterator()),
        "in_bulk": lambda qs: qs.in_bulk([1]),
        "actualizar": lambda qs: qs.update(pk=1),
        "borrar": lambda qs: qs.filter(pk=-1).delete(),
    }

    @parametrizar_tablas
    @pytest.mark.parametrize("operacion", list(OPERACIONES))
    def test_operacion_sin_almacen_lanza_error(self, modelo, operacion, datos_a):
        with pytest.raises(ConsultaSinAlmacenError):
            self.OPERACIONES[operacion](modelo.objects)

    @parametrizar_tablas
    def test_filtrar_a_mano_por_id_almacen_no_reemplaza_a_del_almacen(self, modelo, datos_a):
        with pytest.raises(ConsultaSinAlmacenError):
            list(modelo.objects.filter(id_almacen=datos_a.almacen.pk))

    def test_del_almacen_exige_un_almacen(self):
        with pytest.raises(ValueError):
            Producto.objects.del_almacen(None)

    def test_no_se_puede_refijar_a_otro_almacen(self, datos_a, datos_b):
        with pytest.raises(ConsultaSinAlmacenError):
            Producto.objects.del_almacen(datos_a.almacen).del_almacen(datos_b.almacen)


@pytest.mark.django_db
class TestUnAlmacenNoVeAlOtro:
    @parametrizar_tablas
    def test_lee_solo_lo_suyo(self, modelo, datos_a, datos_b):
        propio = TABLAS[modelo][0](datos_a)
        ajeno = TABLAS[modelo][0](datos_b)
        pks = set(modelo.objects.del_almacen(datos_a.almacen).values_list("pk", flat=True))
        assert propio.pk in pks
        assert ajeno.pk not in pks

    @parametrizar_tablas
    def test_cuenta_solo_lo_suyo(self, modelo, datos_a, datos_b):
        esperado = modelo.sin_aislamiento.filter(id_almacen=datos_a.almacen.pk).count()
        assert modelo.objects.del_almacen(datos_a.almacen).count() == esperado
        total = modelo.sin_aislamiento.count()
        assert esperado < total

    @parametrizar_tablas
    def test_no_obtiene_un_registro_ajeno_por_pk(self, modelo, datos_a, datos_b):
        ajeno = TABLAS[modelo][0](datos_b)
        with pytest.raises(modelo.DoesNotExist):
            modelo.objects.del_almacen(datos_a.almacen).get(pk=ajeno.pk)

    @parametrizar_tablas
    def test_no_modifica_un_registro_ajeno(self, modelo, datos_a, datos_b):
        obtener, campo, valor = TABLAS[modelo]
        ajeno = obtener(datos_b)
        original = getattr(ajeno, campo)
        filas = (
            modelo.objects.del_almacen(datos_a.almacen)
            .filter(pk=ajeno.pk)
            .update(**{campo: valor})
        )
        ajeno.refresh_from_db()
        assert filas == 0
        assert getattr(ajeno, campo) == original

    @parametrizar_tablas
    def test_no_borra_un_registro_ajeno(self, modelo, datos_a, datos_b):
        ajeno = TABLAS[modelo][0](datos_b)
        borrados, _ = modelo.objects.del_almacen(datos_a.almacen).filter(pk=ajeno.pk).delete()
        assert borrados == 0
        assert modelo.sin_aislamiento.filter(pk=ajeno.pk).exists()

    @parametrizar_tablas
    def test_modifica_lo_suyo(self, modelo, datos_a, datos_b):
        obtener, campo, valor = TABLAS[modelo]
        propio = obtener(datos_a)
        filas = (
            modelo.objects.del_almacen(datos_a.almacen)
            .filter(pk=propio.pk)
            .update(**{campo: valor})
        )
        assert filas == 1


@pytest.mark.django_db
class TestCreacionDentroDelAlmacen:
    def test_create_fijado_asigna_el_almacen(self, datos_a):
        categoria = Categoria.objects.del_almacen(datos_a.almacen).create(nombre="Lácteos")
        assert categoria.id_almacen_id == datos_a.almacen.pk

    def test_create_fijado_rechaza_otro_almacen(self, datos_a, datos_b):
        with pytest.raises(ConsultaSinAlmacenError):
            Categoria.objects.del_almacen(datos_a.almacen).create(
                nombre="Lácteos", id_almacen=datos_b.almacen
            )


@pytest.mark.django_db
class TestMaquinariaDeDjango:
    @parametrizar_tablas
    def test_el_default_manager_es_el_sin_aislamiento(self, modelo):
        # Django lo usa internamente (admin, auth, validación de unicidad, relaciones).
        assert modelo._default_manager.name == "sin_aislamiento"

    def test_relaciones_inversas_parten_de_un_registro_ya_aislado(self, datos_a):
        assert list(datos_a.venta.detalles.all()) == [datos_a.detalle]

    def test_login_encuentra_al_usuario_por_email(self, datos_a, client):
        assert client.login(email="vendedor.a@ficticio.test", password="clave-de-prueba")
