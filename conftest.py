"""
Fixtures compartidas. Todos los datos son FICTICIOS, creados sólo para pruebas:
no provienen del almacén piloto ni de ningún almacén real.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from apps.almacenes.models import Almacen
from apps.almacenes.servicios import crear_almacen
from apps.inventario.models import Categoria, MovimientoStock, Producto, TipoMovimiento
from apps.reporteria.models import AccesoReporte
from apps.usuarios.models import RolUsuario, Usuario
from apps.ventas.models import DetalleVenta, MedioPago, Venta


@dataclass
class DatosAlmacen:
    almacen: Almacen
    admin: Usuario
    vendedor: Usuario
    categoria: Categoria
    producto: Producto
    venta: Venta
    detalle: DetalleVenta
    movimiento: MovimientoStock
    acceso: AccesoReporte


def poblar_almacen(sufijo, rut):
    almacen = crear_almacen(razon_social=f"Almacén Ficticio {sufijo}", rut=rut, plan="basico")
    admin = Usuario.sin_aislamiento.create_user(
        email=f"admin.{sufijo.lower()}@ficticio.test",
        nombre=f"Admin Ficticio {sufijo}",
        password="clave-de-prueba",
        rol=RolUsuario.ADMIN,
        id_almacen=almacen,
    )
    vendedor = Usuario.sin_aislamiento.create_user(
        email=f"vendedor.{sufijo.lower()}@ficticio.test",
        nombre=f"Vendedor Ficticio {sufijo}",
        password="clave-de-prueba",
        id_almacen=almacen,
    )
    categoria = Categoria.objects.del_almacen(almacen).create(nombre="Bebidas")
    producto = Producto.objects.del_almacen(almacen).create(
        id_categoria=categoria,
        codigo_barras="7800000000017",
        nombre=f"Bebida Ficticia {sufijo}",
        precio=Decimal("1000"),
        stock_actual=10,
        stock_minimo=2,
    )
    venta = Venta.objects.del_almacen(almacen).create(
        id_usuario=vendedor, total=Decimal("2000"), medio_pago=MedioPago.EFECTIVO
    )
    detalle = DetalleVenta.objects.del_almacen(almacen).create(
        id_venta=venta,
        id_producto=producto,
        cantidad=2,
        precio_unitario=Decimal("1000"),
        subtotal=Decimal("2000"),
    )
    movimiento = MovimientoStock.objects.del_almacen(almacen).create(
        id_producto=producto,
        id_venta=venta,
        id_usuario=vendedor,
        tipo=TipoMovimiento.SALIDA,
        cantidad=2,
    )
    acceso = AccesoReporte.objects.del_almacen(almacen).create(
        id_usuario=admin, mes_consultado=date(2026, 9, 1)
    )
    return DatosAlmacen(
        almacen, admin, vendedor, categoria, producto, venta, detalle, movimiento, acceso
    )


def usuario_de(almacen, rol=RolUsuario.ADMIN):
    """Un usuario ficticio del almacén (lo crea si no existe) para firmar operaciones."""
    existente = Usuario.objects.del_almacen(almacen).filter(rol=rol).first()
    if existente:
        return existente
    return Usuario.sin_aislamiento.create_user(
        email=f"{rol}.{almacen.pk}@ficticio.test",
        nombre=f"Usuario Ficticio {almacen.pk}",
        password="clave-de-prueba",
        rol=rol,
        id_almacen=almacen,
    )


@pytest.fixture(autouse=True)
def hasher_rapido(settings):
    # PBKDF2 con su costo real hace que cada usuario de prueba tarde ~1 s.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def datos_a(db):
    return poblar_almacen("A", "76000001-1")


@pytest.fixture
def datos_b(db):
    return poblar_almacen("B", "76000002-2")


@pytest.fixture
def almacen(db):
    return crear_almacen(razon_social="Almacén Ficticio", rut="76000009-9", plan="basico")
