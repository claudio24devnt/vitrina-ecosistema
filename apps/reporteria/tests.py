from datetime import datetime, time, timezone as tz
from decimal import Decimal

import pytest
from django.db.models import Value
from django.db.models.fields import TimeField

from apps.almacenes.models import FranjaHoraria, condicion_franja
from apps.reporteria.servicios import anotar_franja
from apps.ventas.models import MedioPago, Venta


def _franjas_que_contienen(almacen, hora):
    return list(
        FranjaHoraria.objects.del_almacen(almacen)
        .filter(condicion_franja(Value(hora, output_field=TimeField())))
        .values_list("nombre", flat=True)
    )


def _venta_en(datos, momento_utc):
    return Venta.objects.del_almacen(datos.almacen).create(
        id_usuario=datos.vendedor,
        total=Decimal("1000"),
        medio_pago=MedioPago.EFECTIVO,
        fecha_hora=momento_utc,
    )


def _franja_de(datos, venta):
    ventas = Venta.objects.del_almacen(datos.almacen).filter(pk=venta.pk)
    return anotar_franja(ventas, datos.almacen).get().franja


@pytest.mark.django_db
class TestAsignacionDeFranja:
    def test_cada_minuto_del_dia_cae_en_exactamente_una_franja(self, almacen):
        # Cierra el hueco de hora_fin inclusiva y verifica que no haya traslapes.
        sin_franja, con_varias = [], []
        for minuto in range(24 * 60):
            hora = time(minuto // 60, minuto % 60)
            nombres = _franjas_que_contienen(almacen, hora)
            if not nombres:
                sin_franja.append(hora)
            elif len(nombres) > 1:
                con_varias.append((hora, nombres))
        assert sin_franja == []
        assert con_varias == []

    @pytest.mark.parametrize(
        "hora,esperada",
        [
            (time(10, 59, 30), "Mañana"),
            (time(11, 0), "Mediodía"),
            (time(21, 59, 59), "Noche"),
            (time(22, 0), "Resto"),
            (time(6, 59, 59), "Resto"),
            (time(7, 0), "Mañana"),
        ],
    )
    def test_bordes_de_franja(self, almacen, hora, esperada):
        assert _franjas_que_contienen(almacen, hora) == [esperada]

    def test_venta_a_las_2330_y_a_las_0200_caen_en_resto(self, datos_a):
        # 23:30 y 02:00 hora de Santiago en enero (UTC-3).
        noche = _venta_en(datos_a, datetime(2026, 1, 15, 2, 30, tzinfo=tz.utc))
        madrugada = _venta_en(datos_a, datetime(2026, 1, 15, 5, 0, tzinfo=tz.utc))
        assert _franja_de(datos_a, noche) == "Resto"
        assert _franja_de(datos_a, madrugada) == "Resto"

    def test_usa_hora_de_santiago_y_no_utc_en_verano(self, datos_a):
        # 00:30 UTC del 15 de enero = 21:30 del 14 en Santiago (horario de verano, UTC-3).
        venta = _venta_en(datos_a, datetime(2026, 1, 15, 0, 30, tzinfo=tz.utc))
        assert _franja_de(datos_a, venta) == "Noche"

    def test_usa_hora_de_santiago_y_no_utc_en_invierno(self, datos_a):
        # 14:30 UTC del 15 de julio = 10:30 en Santiago (UTC-4); en UTC sería «Tarde».
        venta = _venta_en(datos_a, datetime(2026, 7, 15, 14, 30, tzinfo=tz.utc))
        assert _franja_de(datos_a, venta) == "Mañana"

    def test_franjas_personalizadas_del_almacen(self, datos_a, datos_b):
        # El almacén A abre a las 09:00: la franja «Resto» se extiende hasta esa hora.
        franjas_a = FranjaHoraria.objects.del_almacen(datos_a.almacen)
        franjas_a.filter(nombre="Mañana").update(hora_inicio=time(9))
        franjas_a.filter(nombre="Resto").update(hora_fin=time(9))
        venta_a = _venta_en(datos_a, datetime(2026, 1, 15, 11, 30, tzinfo=tz.utc))  # 08:30
        venta_b = _venta_en(datos_b, datetime(2026, 1, 15, 11, 30, tzinfo=tz.utc))
        assert _franja_de(datos_a, venta_a) == "Resto"
        assert _franja_de(datos_b, venta_b) == "Mañana"
