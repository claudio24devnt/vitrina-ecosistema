"""
preparar_almacen_carga: deja listo un almacén de plan «carga» para Locust y nunca
toca otro almacén. Datos FICTICIOS (RUT inventados con dígito verificador válido).
"""

from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from apps.almacenes.management.commands.cargar_datos_ficticios import CATALOGO
from apps.almacenes.management.commands.preparar_almacen_carga import (
    STOCK_CARGA,
    codigo_ficticio,
)
from apps.almacenes.servicios import alta_almacen
from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento
from apps.usuarios.models import RolUsuario, Usuario

CLAVE = "Ficticia-2026-segura"
LOCUSTFILE_CODIGOS = [f"20000000{i:05d}" for i in range(24)]


def _almacen(plan, rut="76.000.101-5", email="carga.admin@ficticio.test"):
    almacen, _ = alta_almacen(
        razon_social=f"Almacén Ficticio de {plan}",
        rut=rut,
        plan=plan,
        direccion="",
        nombre_admin="Admin Ficticio",
        email_admin=email,
        password_admin=CLAVE,
    )
    return almacen


def _preparar(rut="76.000.101-5", email="carga.vendedor@ficticio.test", claves=(CLAVE, CLAVE)):
    with mock.patch("getpass.getpass", side_effect=list(claves)):
        call_command(
            "preparar_almacen_carga",
            "--rut",
            rut,
            "--email-vendedor",
            email,
            stdout=mock.MagicMock(),
        )


@pytest.mark.django_db
class TestPrepararAlmacenCarga:
    def test_crea_productos_con_stock_y_vendedor(self):
        almacen = _almacen("carga")
        _preparar()
        productos = Producto.objects.del_almacen(almacen)
        assert productos.count() == len(CATALOGO)
        assert set(productos.values_list("stock_actual", flat=True)) == {STOCK_CARGA}
        # Cada stock inicial deja su movimiento de entrada (regla de §3).
        entradas = MovimientoStock.objects.del_almacen(almacen).filter(
            tipo=TipoMovimiento.ENTRADA
        )
        assert entradas.count() == len(CATALOGO)
        vendedor = Usuario.objects.del_almacen(almacen).get(
            email="carga.vendedor@ficticio.test"
        )
        assert vendedor.rol == RolUsuario.VENDEDOR and vendedor.check_password(CLAVE)

    def test_los_codigos_son_los_del_locustfile(self):
        assert [codigo_ficticio(i) for i in range(len(CATALOGO))] == LOCUSTFILE_CODIGOS

    def test_es_idempotente_y_no_vuelve_a_pedir_clave(self):
        almacen = _almacen("carga")
        _preparar()
        _preparar(claves=())  # sin getpass: si lo pidiera, fallaría
        assert Producto.objects.del_almacen(almacen).count() == len(CATALOGO)

    @pytest.mark.parametrize("plan", ["basico", "piloto"])
    def test_se_niega_con_un_almacen_que_no_es_de_carga(self, plan):
        almacen = _almacen(plan)
        with pytest.raises(CommandError, match="sólo se prepara un almacén de carga"):
            _preparar()
        assert not Producto.objects.del_almacen(almacen).exists()
        assert Usuario.objects.del_almacen(almacen).count() == 1  # sólo su administrador

    def test_rut_inexistente(self, db):
        with pytest.raises(CommandError, match="No hay un almacén con ese RUT"):
            _preparar()

    def test_claves_distintas_no_crean_vendedor(self):
        almacen = _almacen("carga")
        with pytest.raises(CommandError, match="no coinciden"):
            _preparar(claves=(CLAVE, "otra"))
        assert (
            not Usuario.objects.del_almacen(almacen).filter(rol=RolUsuario.VENDEDOR).exists()
        )
