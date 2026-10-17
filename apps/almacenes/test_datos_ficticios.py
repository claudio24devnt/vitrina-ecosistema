"""El comando de datos ficticios respeta las reglas del dominio y sólo toca su almacén."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Sum

from apps.almacenes.management.commands.cargar_datos_ficticios import RUT_FICTICIO
from apps.almacenes.models import Almacen
from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento
from apps.reporteria.servicios import reporte_mensual
from apps.ventas.models import EstadoVenta, Venta


def _cargar(*argumentos):
    call_command("cargar_datos_ficticios", "--dias", "8", *argumentos, stdout=StringIO())
    return Almacen.sin_aislamiento.get(rut=RUT_FICTICIO)


@pytest.mark.django_db
class TestCargarDatosFicticios:
    @pytest.fixture(autouse=True)
    def con_debug(self, settings):
        settings.DEBUG = True

    def test_el_stock_cuadra_con_los_movimientos(self):
        almacen = _cargar()
        for producto in Producto.objects.del_almacen(almacen):
            movimientos = MovimientoStock.objects.del_almacen(almacen).filter(
                id_producto=producto
            )
            suma = {
                tipo: movimientos.filter(tipo=tipo).aggregate(s=Sum("cantidad"))["s"] or 0
                for tipo in TipoMovimiento.values
            }
            esperado = suma["entrada"] - suma["salida"] + suma["ajuste"]
            assert producto.stock_actual == esperado >= 0

    def test_genera_historial_util_para_el_reporte(self):
        almacen = _cargar()
        ventas = Venta.objects.del_almacen(almacen)
        assert ventas.filter(estado=EstadoVenta.VIGENTE).count() > 50
        assert all(v.hora_inicio < v.fecha_hora for v in ventas[:20])
        mes = ventas.order_by("-fecha_hora").first().fecha_hora.date().replace(day=1)
        assert reporte_mensual(almacen, mes).hay_ventas

    def test_no_toca_otros_almacenes_y_exige_limpiar_para_recargar(self, datos_a):
        _cargar()
        with pytest.raises(CommandError, match="--limpiar"):
            _cargar()
        _cargar("--limpiar")
        assert Venta.objects.del_almacen(datos_a.almacen).count() == 1
        assert Almacen.sin_aislamiento.filter(rut=RUT_FICTICIO).count() == 1

    def test_sin_debug_se_niega(self, settings):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="DEBUG"):
            _cargar()
