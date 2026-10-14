from datetime import time

import pytest
from django.db import IntegrityError

from apps.almacenes.models import Almacen, FranjaHoraria
from apps.almacenes.servicios import FRANJAS_INICIALES, crear_almacen


@pytest.mark.django_db
class TestCrearAlmacen:
    def test_crea_las_cinco_franjas_iniciales_en_orden(self, almacen):
        franjas = list(FranjaHoraria.objects.del_almacen(almacen).order_by("orden"))
        assert [(f.nombre, f.orden, f.hora_inicio, f.hora_fin) for f in franjas] == (
            FRANJAS_INICIALES
        )

    def test_valores_por_defecto(self, almacen):
        almacen.refresh_from_db()
        assert almacen.activo is True
        assert almacen.hora_limite_anulacion == time(23, 59)
        assert almacen.fecha_alta is not None

    def test_rut_unico(self, almacen):
        with pytest.raises(IntegrityError):
            Almacen.objects.create(razon_social="Otro", rut=almacen.rut, plan="basico")

    def test_si_falla_no_queda_almacen_sin_franjas(self, almacen, monkeypatch):
        def falla(*args, **kwargs):
            raise RuntimeError("falla forzada")

        monkeypatch.setattr(FranjaHoraria.objects, "bulk_create", falla)
        with pytest.raises(RuntimeError):
            crear_almacen(razon_social="Ficticio 2", rut="76000003-3", plan="basico")
        assert not Almacen.sin_aislamiento.filter(rut="76000003-3").exists()


@pytest.mark.django_db
class TestRestriccionesFranja:
    def test_nombre_unico_por_almacen(self, almacen):
        with pytest.raises(IntegrityError):
            FranjaHoraria.objects.del_almacen(almacen).create(
                nombre="Mañana", orden=9, hora_inicio=time(1), hora_fin=time(2)
            )

    def test_orden_unico_por_almacen(self, almacen):
        with pytest.raises(IntegrityError):
            FranjaHoraria.objects.del_almacen(almacen).create(
                nombre="Otra", orden=1, hora_inicio=time(1), hora_fin=time(2)
            )


@pytest.mark.parametrize(
    "inicio,fin,esperada",
    [
        (time(7), time(11), "07:00 – 10:59"),
        (time(22), time(7), "22:00 – 06:59"),
        (time(18), time(0), "18:00 – 23:59"),
    ],
)
def test_etiqueta_resta_un_minuto_a_hora_fin(inicio, fin, esperada):
    assert FranjaHoraria(hora_inicio=inicio, hora_fin=fin).etiqueta == esperada
