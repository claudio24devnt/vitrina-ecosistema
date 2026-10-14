from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inventario.models import Categoria, MovimientoStock, Producto, TipoMovimiento
from apps.usuarios.models import RolUsuario, Usuario
from apps.ventas.management.commands.cargar_datos_prueba import CATALOGO, codigo_ean13
from apps.ventas.models import EstadoVenta, Venta


@pytest.fixture
def debug(settings):
    settings.DEBUG = True


def cargar(**opciones):
    opciones = {"dias": 5, "ventas_por_dia": 6, **opciones}
    call_command("cargar_datos_prueba", stdout=StringIO(), **opciones)


@pytest.mark.django_db
class TestCargarDatosPrueba:
    def test_crea_catalogo_usuarios_y_ventas(self, debug):
        cargar()

        assert Producto.objects.count() == len(CATALOGO)
        assert Categoria.objects.count() == len({c for c, _, _, _ in CATALOGO})
        assert Usuario.objects.get(email="admin@tivoscanea.cl").rol == RolUsuario.ADMIN
        assert Usuario.objects.get(email="vendedor@tivoscanea.cl").check_password(
            "tivoscanea123"
        )
        assert Venta.objects.count() > 0

    def test_stock_cuadra_con_la_bitacora_de_movimientos(self, debug):
        cargar(dias=10)

        for producto in Producto.objects.all():
            totales = MovimientoStock.objects.filter(id_producto=producto).aggregate(
                entradas=Sum("cantidad", filter=Q(tipo=TipoMovimiento.ENTRADA)),
                salidas=Sum("cantidad", filter=Q(tipo=TipoMovimiento.SALIDA)),
            )
            assert producto.stock_actual == (totales["entradas"] or 0) - (
                totales["salidas"] or 0
            )

    def test_ventas_quedan_dentro_del_rango_y_con_salidas_fechadas(self, debug):
        cargar()
        ahora = timezone.now()
        inicio = timezone.localdate() - timedelta(days=5)

        assert not Venta.objects.filter(fecha_hora__gt=ahora).exists()
        assert not Venta.objects.filter(fecha_hora__date__lt=inicio).exists()
        for venta in Venta.objects.all()[:20]:
            salidas = venta.movimientos_stock.filter(tipo=TipoMovimiento.SALIDA)
            assert salidas.count() == venta.detalles.count()
            assert all(m.fecha_hora == venta.fecha_hora for m in salidas)

    def test_anuladas_reponen_stock(self, debug):
        cargar(dias=30, ventas_por_dia=10)

        anuladas = Venta.objects.filter(estado=EstadoVenta.ANULADA)
        assert anuladas.exists()
        for venta in anuladas:
            assert venta.movimientos_stock.filter(tipo=TipoMovimiento.ENTRADA).count() == (
                venta.detalles.count()
            )

    def test_es_reproducible_con_la_misma_semilla(self, debug):
        cargar(semilla=7)
        primera = list(Venta.objects.order_by("fecha_hora").values_list("total", flat=True))
        cargar(semilla=7, limpiar=True)
        segunda = list(Venta.objects.order_by("fecha_hora").values_list("total", flat=True))
        assert primera == segunda

    def test_caida_reduce_ventas_del_periodo_final(self, debug):
        cargar(dias=20, ventas_por_dia=30, caida_ultimos_dias=10, caida_porcentaje=60)
        hoy = timezone.localdate()
        corte = hoy - timedelta(days=10)
        antes = Venta.objects.filter(
            fecha_hora__date__gt=corte - timedelta(days=9), fecha_hora__date__lte=corte
        ).count()
        despues = Venta.objects.filter(
            fecha_hora__date__gt=corte, fecha_hora__date__lt=hoy
        ).count()
        assert despues < antes * 0.6

    def test_no_duplica_si_ya_hay_datos(self, debug):
        cargar()
        with pytest.raises(CommandError, match="--limpiar"):
            cargar()

    def test_se_niega_con_debug_false(self, settings, db):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="DEBUG=False"):
            cargar()

    def test_parametros_invalidos(self, debug):
        with pytest.raises(CommandError):
            call_command("cargar_datos_prueba", dias=0)


def test_codigo_ean13_tiene_digito_verificador_valido():
    # Suma ponderada de los 12 primeros dígitos + verificador ≡ 0 (mod 10)
    codigo = codigo_ean13(1)
    assert len(codigo) == 13
    suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(codigo))
    assert suma % 10 == 0
