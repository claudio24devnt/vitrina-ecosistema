"""El comando de ventas simuladas (FICTICIAS) no altera el stock y se puede deshacer."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.almacenes.management.commands.simular_ventas import NOMBRE_SIMULADO
from apps.almacenes.models import ZONA_HORARIA_ALMACEN, Almacen
from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento
from apps.reporteria.servicios import inicio_de_registros, mes_anterior, reporte_mensual
from apps.usuarios.models import Usuario
from apps.ventas.models import DetalleVenta, EstadoVenta, Venta


def _desde():
    return mes_anterior(timezone.localdate(timezone=ZONA_HORARIA_ALMACEN).replace(day=1))


def _simular(datos, *extra):
    salida = StringIO()
    call_command(
        "simular_ventas",
        "--email",
        datos.admin.email,
        "--desde",
        f"{_desde():%Y-%m}",
        "--ventas-por-dia",
        "4",
        *extra,
        stdout=salida,
    )
    return salida.getvalue()


def _foto(almacen):
    return (
        dict(Producto.objects.del_almacen(almacen).values_list("pk", "stock_actual")),
        Venta.objects.del_almacen(almacen).count(),
        MovimientoStock.objects.del_almacen(almacen).count(),
        DetalleVenta.objects.del_almacen(almacen).count(),
        Usuario.objects.del_almacen(almacen).count(),
    )


@pytest.mark.django_db
class TestSimularVentas:
    def test_sin_confirmar_no_escribe(self, datos_a):
        antes = _foto(datos_a.almacen)
        assert "Ensayo" in _simular(datos_a)
        assert _foto(datos_a.almacen) == antes

    def test_simula_sin_cambiar_el_stock_ni_tocar_otro_almacen(self, datos_a, datos_b):
        stock_a = _foto(datos_a.almacen)[0]
        foto_b = _foto(datos_b.almacen)
        _simular(datos_a, "--confirmar")

        almacen = datos_a.almacen
        simulado = Usuario.objects.del_almacen(almacen).get(nombre=NOMBRE_SIMULADO)
        assert not simulado.is_active
        ventas = Venta.objects.del_almacen(almacen).filter(id_usuario=simulado)
        assert ventas.count() > 20
        assert all(v.hora_inicio < v.fecha_hora for v in ventas)
        for venta in ventas.filter(estado=EstadoVenta.ANULADA):
            assert venta.fecha_anulacion > venta.fecha_hora
        assert _foto(almacen)[0] == stock_a
        assert not MovimientoStock.objects.del_almacen(almacen).filter(
            tipo=TipoMovimiento.AJUSTE
        )
        assert _foto(datos_b.almacen) == foto_b
        # El primer mes empieza el día 1: queda completo y comparable.
        almacen = Almacen.sin_aislamiento.get(pk=almacen.pk)
        assert inicio_de_registros(almacen) == _desde()
        assert reporte_mensual(almacen, _desde()).hay_ventas

    def test_deshacer_deja_todo_como_estaba(self, datos_a):
        antes = _foto(datos_a.almacen)
        _simular(datos_a, "--confirmar")
        with pytest.raises(CommandError, match="--deshacer"):
            _simular(datos_a, "--confirmar")
        assert "Ensayo" in _simular(datos_a, "--deshacer")
        _simular(datos_a, "--deshacer", "--confirmar")
        assert _foto(datos_a.almacen) == antes

    def test_rechaza_correo_que_no_es_de_administrador(self, datos_a):
        with pytest.raises(CommandError, match="administrador"):
            call_command(
                "simular_ventas", "--email", datos_a.vendedor.email, "--desde", "2026-08"
            )

    def test_rechaza_almacen_de_operacion(self, datos_a):
        Almacen.sin_aislamiento.filter(pk=datos_a.almacen.pk).update(plan="operacion")
        with pytest.raises(CommandError, match="operacion"):
            _simular(datos_a, "--confirmar")
