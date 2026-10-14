from datetime import datetime, time, timedelta, timezone as tz
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.almacenes.models import ZONA_HORARIA_ALMACEN
from apps.ventas.models import DetalleVenta, EstadoVenta, MedioPago, Venta
from apps.ventas.servicios import anulacion_en_plazo, limite_anulacion


def _venta(datos, **campos):
    valores = {
        "id_usuario": datos.vendedor,
        "total": Decimal("1000"),
        "medio_pago": MedioPago.EFECTIVO,
    }
    valores.update(campos)
    return Venta.objects.del_almacen(datos.almacen).create(**valores)


def _santiago(*args):
    return datetime(*args, tzinfo=ZONA_HORARIA_ALMACEN)


@pytest.mark.django_db
class TestRestriccionesVenta:
    def test_estado_invalido(self, datos_a):
        with pytest.raises(IntegrityError):
            _venta(datos_a, estado="borrada")

    def test_estado_por_defecto_vigente(self, datos_a):
        assert datos_a.venta.estado == EstadoVenta.VIGENTE

    def test_cantidad_debe_ser_mayor_que_cero(self, datos_a):
        with pytest.raises(IntegrityError):
            DetalleVenta.objects.del_almacen(datos_a.almacen).create(
                id_venta=datos_a.venta,
                id_producto=datos_a.producto,
                cantidad=0,
                precio_unitario=Decimal("1000"),
                subtotal=Decimal("0"),
            )

    def test_hora_inicio_es_opcional(self, datos_a):
        assert datos_a.venta.hora_inicio is None
        venta = _venta(datos_a, hora_inicio=timezone.now() - timedelta(seconds=40))
        assert venta.hora_inicio < venta.fecha_hora


@pytest.mark.django_db
class TestAuditoriaDeAnulacion:
    """ck_venta_anulacion_coherente y ck_venta_anulacion_posterior: los rechaza la BD."""

    def _anulacion(self, datos, **cambios):
        campos = {
            "estado": EstadoVenta.ANULADA,
            "id_usuario_anulacion": datos.admin,
            "fecha_anulacion": timezone.now() + timedelta(minutes=1),
            "motivo_anulacion": "Cliente devolvió el producto",
        }
        campos.update(cambios)
        return campos

    def test_anulacion_completa_es_aceptada(self, datos_a):
        venta = _venta(datos_a, **self._anulacion(datos_a))
        assert venta.estado == EstadoVenta.ANULADA

    def test_vigente_con_autor_de_anulacion_es_rechazada_por_la_bd(self, datos_a):
        with pytest.raises(IntegrityError):
            Venta.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.venta.pk).update(
                id_usuario_anulacion=datos_a.admin
            )

    @pytest.mark.parametrize("campo", ["fecha_anulacion", "motivo_anulacion"])
    def test_vigente_con_cualquier_campo_de_anulacion_es_rechazada(self, datos_a, campo):
        valor = timezone.now() if campo == "fecha_anulacion" else "Motivo cualquiera"
        with pytest.raises(IntegrityError):
            _venta(datos_a, **{campo: valor})

    @pytest.mark.parametrize(
        "campo", ["id_usuario_anulacion", "fecha_anulacion", "motivo_anulacion"]
    )
    def test_anulada_sin_alguno_de_los_tres_campos_es_rechazada(self, datos_a, campo):
        with pytest.raises(IntegrityError):
            _venta(datos_a, **self._anulacion(datos_a, **{campo: None}))

    @pytest.mark.parametrize("motivo", ["x", ".", "    ", "  ab  ", "abcd"])
    def test_motivo_de_menos_de_cinco_caracteres_utiles_es_rechazado(self, datos_a, motivo):
        with pytest.raises(IntegrityError):
            _venta(datos_a, **self._anulacion(datos_a, motivo_anulacion=motivo))

    def test_motivo_de_cinco_caracteres_es_aceptado(self, datos_a):
        assert _venta(datos_a, **self._anulacion(datos_a, motivo_anulacion="  Error  "))

    def test_anulacion_anterior_a_la_venta_es_rechazada(self, datos_a):
        with pytest.raises(IntegrityError):
            _venta(
                datos_a,
                **self._anulacion(
                    datos_a, fecha_anulacion=timezone.now() - timedelta(hours=1)
                ),
            )


@pytest.mark.django_db
class TestPlazoDeAnulacion:
    def test_limite_por_defecto_es_el_fin_del_dia_de_la_venta(self, datos_a):
        venta = _venta(datos_a, fecha_hora=_santiago(2026, 10, 14, 10, 0))
        assert limite_anulacion(venta) == _santiago(2026, 10, 15, 0, 0)

    @pytest.mark.parametrize(
        "momento,permitido",
        [
            (_santiago(2026, 10, 14, 10, 5), True),
            (_santiago(2026, 10, 14, 23, 58), True),
            (_santiago(2026, 10, 14, 23, 59, 30), True),
            (_santiago(2026, 10, 15, 0, 0, 30), False),
            (_santiago(2026, 10, 16, 9, 0), False),
        ],
    )
    def test_antes_del_plazo_se_acepta_despues_se_rechaza(self, datos_a, momento, permitido):
        venta = _venta(datos_a, fecha_hora=_santiago(2026, 10, 14, 10, 0))
        assert anulacion_en_plazo(venta, momento) is permitido

    def test_el_dia_se_cuenta_en_hora_de_santiago_no_en_utc(self, datos_a):
        # 01:00 UTC del 15 de enero = 22:00 del 14 en Santiago: el plazo vence el 14.
        venta = _venta(datos_a, fecha_hora=datetime(2026, 1, 15, 1, 0, tzinfo=tz.utc))
        assert anulacion_en_plazo(venta, _santiago(2026, 1, 14, 23, 30)) is True
        assert anulacion_en_plazo(venta, _santiago(2026, 1, 15, 0, 30)) is False

    def test_plazo_parametrizable_por_almacen(self, datos_a, datos_b):
        datos_a.almacen.hora_limite_anulacion = time(20, 0)
        datos_a.almacen.save()
        venta_a = _venta(datos_a, fecha_hora=_santiago(2026, 10, 14, 10, 0))
        venta_b = _venta(datos_b, fecha_hora=_santiago(2026, 10, 14, 10, 0))
        momento = _santiago(2026, 10, 14, 20, 30)
        assert anulacion_en_plazo(venta_a, momento) is False
        assert anulacion_en_plazo(venta_b, momento) is True
