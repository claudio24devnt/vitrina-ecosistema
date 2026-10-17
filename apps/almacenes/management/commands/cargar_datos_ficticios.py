"""
DATOS FICTICIOS para desarrollo y revisión local. No provienen del almacén piloto
ni de ningún almacén real: el almacén, las personas, los productos, los precios y
los patrones de venta (más venta el fin de semana y al mediodía) son INVENTADOS y
no son una medición. No usar para estimar indicadores (§2.3 y §7).

Crea un almacén de demostración con un administrador, una vendedora, productos y
un historial de ventas de N días. Todo pasa por los servicios de negocio, así que
cada variación de stock deja su movimiento como en uso real; después se «envejece»
cada registro a su fecha simulada con un update().

Sólo corre con DEBUG activo, para que nunca toque una base de producción.

    python manage.py cargar_datos_ficticios
    python manage.py cargar_datos_ficticios --dias 150 --semilla 7
    python manage.py cargar_datos_ficticios --limpiar
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.almacenes.models import ZONA_HORARIA_ALMACEN, Almacen, FranjaHoraria
from apps.almacenes.servicios import crear_almacen
from apps.inventario.models import Categoria, MovimientoStock, Producto
from apps.inventario.servicios import (
    productos_con_stock_bajo,
    registrar_entrada_stock,
    registrar_producto,
)
from apps.reporteria.models import AccesoReporte, Alerta
from apps.usuarios.models import RolUsuario, Usuario
from apps.ventas.models import DetalleVenta, MedioPago, Venta
from apps.ventas.servicios import LineaVenta, anular_venta, registrar_venta

RUT_FICTICIO = "76999999-9"
RAZON_SOCIAL = "Almacén Ficticio Los Aromos"
CLAVE = "clave-ficticia-123"
USUARIOS = [
    ("admin@demo.ficticio.test", "Marta Ficticia", RolUsuario.ADMIN),
    ("vendedora@demo.ficticio.test", "Javiera Ficticia", RolUsuario.VENDEDOR),
]

# (categoría, nombre, precio, stock mínimo, popularidad relativa). Inventados.
# Prefijo 2 (EAN de uso interno): no choca con códigos reales escaneados.
CATALOGO = [
    ("Panadería", "Pan Ficticio (kg)", 1990, 5, 10),
    ("Panadería", "Hallulla Ficticia (unidad)", 250, 20, 8),
    ("Bebidas", "Bebida Cola Ficticia 1,5 L", 1800, 6, 7),
    ("Bebidas", "Agua Mineral Ficticia 1,6 L", 1100, 6, 4),
    ("Bebidas", "Jugo Ficticio 1 L", 1290, 4, 3),
    ("Bebidas", "Cerveza Ficticia lata 470 cc", 1350, 12, 5),
    ("Lácteos", "Leche Ficticia 1 L", 1150, 8, 7),
    ("Lácteos", "Yogur Ficticio 125 g", 450, 10, 4),
    ("Lácteos", "Queso Ficticio laminado 250 g", 3290, 3, 2),
    ("Lácteos", "Mantequilla Ficticia 250 g", 2490, 3, 2),
    ("Abarrotes", "Arroz Ficticio 1 kg", 1590, 5, 3),
    ("Abarrotes", "Fideos Ficticios 400 g", 990, 6, 4),
    ("Abarrotes", "Aceite Ficticio 1 L", 2890, 3, 2),
    ("Abarrotes", "Azúcar Ficticia 1 kg", 1290, 4, 3),
    ("Abarrotes", "Té Ficticio 100 bolsitas", 2190, 2, 1),
    ("Abarrotes", "Café Ficticio 170 g", 4590, 2, 1),
    ("Abarrotes", "Salsa de Tomate Ficticia 200 g", 690, 6, 3),
    ("Snacks", "Papas Fritas Ficticias 180 g", 1990, 4, 3),
    ("Snacks", "Galletas Ficticias 120 g", 790, 8, 5),
    ("Snacks", "Chocolate Ficticio 100 g", 1490, 4, 3),
    ("Aseo", "Detergente Ficticio 1 kg", 3990, 2, 1),
    ("Aseo", "Papel Higiénico Ficticio x4", 2690, 3, 2),
    ("Aseo", "Lavaloza Ficticio 500 ml", 1490, 2, 1),
    ("Aseo", "Cloro Ficticio 1 L", 990, 2, 1),
]

# Ventas promedio por día de la semana (lunes=0) y peso de cada hora del día.
VENTAS_POR_DIA = [18, 16, 16, 18, 24, 30, 22]
PESO_HORA = {
    7: 3, 8: 6, 9: 5, 10: 4, 11: 5, 12: 8, 13: 8, 14: 4, 15: 3, 16: 3,
    17: 5, 18: 7, 19: 8, 20: 6, 21: 3, 22: 1,
}  # fmt: skip
MEDIOS = [MedioPago.EFECTIVO] * 5 + [MedioPago.DEBITO] * 4 + [MedioPago.TRANSFERENCIA]
PROPORCION_ANULADAS = 0.02


def _ultimo_pk(modelo, almacen):
    return modelo.objects.del_almacen(almacen).aggregate(m=Max("pk"))["m"] or 0


class Command(BaseCommand):
    help = "Carga un almacén de demostración con DATOS FICTICIOS (sólo con DEBUG)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=120, help="Días de historial.")
        parser.add_argument("--semilla", type=int, default=2026, help="Semilla aleatoria.")
        parser.add_argument(
            "--limpiar",
            action="store_true",
            help="Borra el almacén de demostración (y sólo ése) antes de cargarlo.",
        )

    def handle(self, *args, dias, semilla, limpiar, **opciones):
        if not settings.DEBUG:
            raise CommandError("Sólo se cargan datos ficticios con DEBUG activo.")
        if dias < 1:
            raise CommandError("--dias debe ser al menos 1.")
        existente = Almacen.sin_aislamiento.filter(rut=RUT_FICTICIO).first()
        if existente and not limpiar:
            raise CommandError(
                "El almacén de demostración ya existe. Usa --limpiar para recrearlo."
            )
        azar = random.Random(semilla)
        with transaction.atomic():
            if existente:
                self._borrar(existente)
            almacen, admin, vendedora = self._crear_almacen(dias)
            productos = self._crear_productos(almacen, admin, dias)
            cantidad = self._simular_ventas(almacen, admin, vendedora, productos, dias, azar)

        self.stdout.write(self.style.SUCCESS(f"{RAZON_SOCIAL}: {cantidad} ventas ficticias."))
        for email, _, rol in USUARIOS:
            self.stdout.write(f"  {rol:<9} {email} / {CLAVE}")

    def _borrar(self, almacen):
        # Orden inverso a las FK protegidas; todo fijado al almacén de demostración.
        for modelo in [
            Alerta,
            AccesoReporte,
            MovimientoStock,
            DetalleVenta,
            Venta,
            Producto,
            Categoria,
            FranjaHoraria,
            Usuario,
        ]:
            modelo.objects.del_almacen(almacen).delete()
        Almacen.objects.del_almacen(almacen).delete()

    def _crear_almacen(self, dias):
        almacen = crear_almacen(
            razon_social=RAZON_SOCIAL,
            rut=RUT_FICTICIO,
            plan="basico",
            direccion="Calle Ficticia 123, Comuna Ficticia",
        )
        inicio = timezone.now() - timedelta(days=dias + 1)
        Almacen.objects.del_almacen(almacen).update(fecha_alta=inicio)
        almacen.refresh_from_db()
        usuarios = [
            Usuario.sin_aislamiento.create_user(
                email=email, nombre=nombre, password=CLAVE, rol=rol, id_almacen=almacen
            )
            for email, nombre, rol in USUARIOS
        ]
        return almacen, *usuarios

    def _crear_productos(self, almacen, admin, dias):
        inicio = timezone.now() - timedelta(days=dias + 1)
        categorias = {}
        productos = []
        for indice, (categoria, nombre, precio, minimo, popularidad) in enumerate(CATALOGO):
            if categoria not in categorias:
                categorias[categoria] = Categoria.objects.del_almacen(almacen).create(
                    nombre=categoria
                )
            producto = registrar_producto(
                almacen=almacen,
                usuario=admin,
                codigo_barras=f"20000000{indice:05d}",
                nombre=nombre,
                precio=Decimal(precio),
                categoria=categorias[categoria],
                stock_minimo=minimo,
                stock_inicial=minimo * 4,
            )
            productos.append((producto, popularidad))
        Producto.objects.del_almacen(almacen).update(fecha_creacion=inicio)
        MovimientoStock.objects.del_almacen(almacen).update(fecha_hora=inicio)
        return productos

    def _simular_ventas(self, almacen, admin, vendedora, productos, dias, azar):
        hoy = timezone.localdate(timezone=ZONA_HORARIA_ALMACEN)
        horas, pesos_hora = zip(*PESO_HORA.items())
        catalogo, popularidad = zip(*productos)
        total = 0
        for atras in range(dias, -1, -1):
            dia = hoy - timedelta(days=atras)
            cantidad = max(0, round(azar.gauss(VENTAS_POR_DIA[dia.weekday()], 4)))
            momentos = sorted(
                datetime.combine(
                    dia,
                    time(azar.choices(horas, pesos_hora)[0], azar.randrange(60)),
                    tzinfo=ZONA_HORARIA_ALMACEN,
                )
                for _ in range(cantidad)
            )
            if atras == 0:  # hoy: sólo hasta la hora actual
                momentos = [m for m in momentos if m <= timezone.now()]
            for momento in momentos:
                # Los dos últimos días no se repone: así el panel tiene stock bajo que mostrar.
                if atras > 1:
                    self._reponer(almacen, admin, momento - timedelta(minutes=1))
                elegidos = set(azar.choices(catalogo, popularidad, k=azar.randint(1, 4)))
                lineas = [(p.pk, azar.choice([1, 1, 1, 2, 2, 3])) for p in elegidos]
                usuario = azar.choice([admin, vendedora, vendedora])
                total += self._vender(almacen, usuario, lineas, momento, azar)
        return total

    def _reponer(self, almacen, admin, momento):
        """Repone lo que quedó en o bajo el mínimo, con la entrada fechada en `momento`."""
        desde = _ultimo_pk(MovimientoStock, almacen)
        for producto in productos_con_stock_bajo(almacen):
            registrar_entrada_stock(
                almacen=almacen,
                producto=producto,
                cantidad=producto.stock_minimo * 4,
                usuario=admin,
            )
        MovimientoStock.objects.del_almacen(almacen).filter(pk__gt=desde).update(
            fecha_hora=momento
        )

    def _vender(self, almacen, usuario, lineas, momento, azar):
        # Sin reposición se vende sólo lo que hay; si no queda nada, no hay venta.
        stock = dict(
            Producto.objects.del_almacen(almacen)
            .filter(pk__in=[pk for pk, _ in lineas])
            .values_list("pk", "stock_actual")
        )
        lineas = [(pk, cantidad) for pk, cantidad in lineas if stock[pk] >= cantidad]
        if not lineas:
            return False
        desde = _ultimo_pk(MovimientoStock, almacen)
        venta = registrar_venta(
            almacen=almacen,
            usuario=usuario,
            lineas=[LineaVenta(id_producto=pk, cantidad=cantidad) for pk, cantidad in lineas],
            medio_pago=azar.choice(MEDIOS),
        )
        cambios = {
            "fecha_hora": momento,
            "hora_inicio": momento - timedelta(seconds=azar.randint(20, 120)),
        }
        if azar.random() < PROPORCION_ANULADAS:
            venta = anular_venta(
                almacen=almacen, venta=venta, usuario=usuario, motivo="Error ficticio de caja"
            )
            cambios["fecha_anulacion"] = momento + timedelta(minutes=3)
        Venta.objects.del_almacen(almacen).filter(pk=venta.pk).update(**cambios)
        MovimientoStock.objects.del_almacen(almacen).filter(pk__gt=desde).update(
            fecha_hora=momento
        )
        return True
