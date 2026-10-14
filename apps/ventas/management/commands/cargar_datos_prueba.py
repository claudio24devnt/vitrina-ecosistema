"""
Carga datos de prueba realistas para desarrollo y para probar la reportería:
~50 productos de almacén de barrio y un historial de ventas de N días.

Todo pasa por los servicios de negocio (crear_producto_con_stock_inicial,
registrar_entrada_stock, registrar_venta, anular_venta), así que cada
variación de stock deja su MovimientoStock igual que en uso real. Como
fecha_hora/fecha_creacion son auto_now_add, después de crear cada registro
se "envejece" con un update() a la fecha simulada.

Uso:
    python manage.py cargar_datos_prueba
    python manage.py cargar_datos_prueba --dias 120 --semilla 7
    python manage.py cargar_datos_prueba --limpiar --caida-ultimos-dias 30
"""

import random
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.inventario.models import Categoria, MovimientoStock, Producto, TipoMovimiento
from apps.inventario.services import crear_producto_con_stock_inicial, registrar_entrada_stock
from apps.usuarios.models import RolUsuario, Usuario
from apps.ventas.models import DetalleVenta, MedioPago, Venta
from apps.ventas.services import anular_venta, registrar_venta

# Prefijo EAN-13 "780" (Chile) + "9999" para que los productos de prueba
# se reconozcan a simple vista y no choquen con códigos reales escaneados.
PREFIJO_CODIGO = "7809999"

PASSWORD_PRUEBA = "tivoscanea123"
USUARIOS_PRUEBA = [
    ("admin@tivoscanea.cl", "Rosa Muñoz", RolUsuario.ADMIN),
    ("vendedor@tivoscanea.cl", "Pedro Soto", RolUsuario.VENDEDOR),
]

# (categoría, nombre, precio CLP, popularidad relativa)
CATALOGO = [
    ("Bebidas", "Coca-Cola 1.5L", 1990, 9),
    ("Bebidas", "Coca-Cola Zero 1.5L", 1990, 5),
    ("Bebidas", "Fanta 1.5L", 1790, 4),
    ("Bebidas", "Sprite 1.5L", 1790, 3),
    ("Bebidas", "Agua Mineral sin gas 1.6L", 990, 6),
    ("Bebidas", "Agua Mineral con gas 500ml", 690, 4),
    ("Bebidas", "Jugo en polvo naranja", 290, 5),
    ("Bebidas", "Néctar durazno 1L", 1290, 3),
    ("Bebidas", "Cerveza lata 470ml", 1100, 7),
    ("Bebidas", "Bebida energética 473ml", 1490, 3),
    ("Lácteos", "Leche entera 1L", 1090, 9),
    ("Lácteos", "Leche descremada 1L", 1090, 5),
    ("Lácteos", "Yogur batido frutilla 165g", 450, 6),
    ("Lácteos", "Queso gauda laminado 250g", 3290, 4),
    ("Lácteos", "Mantequilla con sal 250g", 2490, 4),
    ("Lácteos", "Huevos blancos x12", 3490, 7),
    ("Panadería", "Marraqueta (kg)", 2200, 10),
    ("Panadería", "Hallulla (kg)", 2200, 8),
    ("Panadería", "Pan de molde blanco", 2190, 4),
    ("Panadería", "Queque de vainilla", 1990, 2),
    ("Abarrotes", "Arroz grado 1 1kg", 1490, 6),
    ("Abarrotes", "Fideos spaghetti 400g", 890, 7),
    ("Abarrotes", "Aceite vegetal 1L", 2490, 4),
    ("Abarrotes", "Azúcar 1kg", 1290, 5),
    ("Abarrotes", "Harina sin polvos 1kg", 1190, 3),
    ("Abarrotes", "Sal fina 1kg", 590, 2),
    ("Abarrotes", "Té 100 bolsitas", 2290, 4),
    ("Abarrotes", "Café instantáneo 170g", 4990, 3),
    ("Abarrotes", "Salsa de tomate 200g", 490, 6),
    ("Abarrotes", "Atún en aceite 160g", 1590, 4),
    ("Abarrotes", "Porotos en tarro 380g", 1190, 2),
    ("Abarrotes", "Mayonesa 372g", 1890, 4),
    ("Snacks y dulces", "Papas fritas 230g", 2290, 6),
    ("Snacks y dulces", "Ramitas 160g", 1190, 4),
    ("Snacks y dulces", "Galletas de chocolate 120g", 690, 8),
    ("Snacks y dulces", "Galletas de soda 3-pack", 990, 3),
    ("Snacks y dulces", "Chocolate de leche 100g", 1490, 5),
    ("Snacks y dulces", "Caramelos masticables", 150, 6),
    ("Snacks y dulces", "Chicle menta", 300, 4),
    ("Limpieza", "Cloro 1L", 990, 4),
    ("Limpieza", "Lavaloza 750ml", 1490, 4),
    ("Limpieza", "Detergente en polvo 1kg", 3490, 2),
    ("Limpieza", "Papel higiénico 4 rollos", 2490, 6),
    ("Limpieza", "Toalla de papel 2 rollos", 1990, 3),
    ("Limpieza", "Bolsas de basura x10", 990, 3),
    ("Aseo personal", "Pasta dental 90g", 1590, 3),
    ("Aseo personal", "Jabón en barra", 790, 3),
    ("Aseo personal", "Shampoo 400ml", 2990, 2),
    ("Aseo personal", "Desodorante spray", 2790, 2),
    ("Aseo personal", "Pañales talla G x30", 9990, 2),
]

MEDIOS_PAGO = [
    (MedioPago.EFECTIVO, 45),
    (MedioPago.DEBITO, 35),
    (MedioPago.TRANSFERENCIA, 15),
    (MedioPago.CREDITO, 5),
]

# Hora -> peso relativo: picos al desayuno, almuerzo y salida del trabajo.
PESOS_HORA = {
    8: 4, 9: 5, 10: 3, 11: 3, 12: 5, 13: 7, 14: 5, 15: 3,
    16: 3, 17: 5, 18: 8, 19: 9, 20: 7, 21: 4,
}  # fmt: skip

PORCENTAJE_ANULADAS = 2


def codigo_ean13(indice):
    base = f"{PREFIJO_CODIGO}{indice:05d}"
    suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base))
    return base + str((10 - suma % 10) % 10)


class Command(BaseCommand):
    help = "Carga ~50 productos y un historial de ventas de prueba (sólo desarrollo)."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=90, help="Días de historial (90).")
        parser.add_argument(
            "--ventas-por-dia", type=int, default=25, help="Promedio de ventas diarias (25)."
        )
        parser.add_argument("--semilla", type=int, default=42, help="Semilla aleatoria (42).")
        parser.add_argument(
            "--caida-ultimos-dias",
            type=int,
            default=0,
            help="Simula una caída de ventas en los últimos N días (para probar la alerta).",
        )
        parser.add_argument(
            "--caida-porcentaje",
            type=int,
            default=25,
            help="Porcentaje de caída a simular cuando se usa --caida-ultimos-dias (25).",
        )
        parser.add_argument(
            "--limpiar",
            action="store_true",
            help="Borra TODAS las ventas, movimientos, productos y categorías antes.",
        )
        parser.add_argument(
            "--forzar",
            action="store_true",
            help="Permite correr con DEBUG=False (no usar en producción).",
        )

    def handle(self, *args, **opciones):
        if not settings.DEBUG and not opciones["forzar"]:
            raise CommandError(
                "DEBUG=False: este comando es sólo para desarrollo (usá --forzar)."
            )
        if opciones["dias"] < 1 or opciones["ventas_por_dia"] < 1:
            raise CommandError("--dias y --ventas-por-dia deben ser mayores que cero.")

        self.azar = random.Random(opciones["semilla"])
        self.tz = timezone.get_current_timezone()

        with transaction.atomic():
            if opciones["limpiar"]:
                self._limpiar()
            elif Producto.objects.filter(codigo_barras__startswith=PREFIJO_CODIGO).exists():
                raise CommandError(
                    "Ya hay datos de prueba cargados. Usá --limpiar para regenerarlos."
                )

            admin, vendedor = self._crear_usuarios()
            hoy = timezone.localdate()
            inicio = hoy - timedelta(days=opciones["dias"])
            productos = self._crear_productos(inicio)
            total_ventas = self._crear_ventas(
                productos=productos,
                vendedores=[admin, vendedor, vendedor],
                admin=admin,
                inicio=inicio,
                hoy=hoy,
                ventas_por_dia=opciones["ventas_por_dia"],
                caida_dias=opciones["caida_ultimos_dias"],
                caida_porcentaje=opciones["caida_porcentaje"],
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {len(productos)} productos y {total_ventas} ventas "
                f"entre {inicio:%d/%m/%Y} y {hoy:%d/%m/%Y}."
            )
        )
        self.stdout.write(
            "Usuarios de prueba (password «"
            + PASSWORD_PRUEBA
            + "»): "
            + ", ".join(email for email, _, _ in USUARIOS_PRUEBA)
        )

    def _limpiar(self):
        MovimientoStock.objects.all().delete()
        DetalleVenta.objects.all().delete()
        Venta.objects.all().delete()
        Producto.objects.all().delete()
        Categoria.objects.all().delete()
        self.stdout.write("Datos de inventario y ventas borrados.")

    def _crear_usuarios(self):
        usuarios = []
        for email, nombre, rol in USUARIOS_PRUEBA:
            usuario = Usuario.objects.filter(email=email).first()
            if usuario is None:
                usuario = Usuario.objects.create_user(
                    email=email, nombre=nombre, password=PASSWORD_PRUEBA, rol=rol
                )
            usuarios.append(usuario)
        return usuarios

    def _fecha(self, dia, hora, minuto=0, segundo=0):
        return timezone.make_aware(datetime.combine(dia, time(hora, minuto, segundo)), self.tz)

    def _crear_productos(self, inicio):
        fecha_alta = self._fecha(inicio - timedelta(days=1), 9)
        categorias = {}
        productos = []
        for indice, (nombre_cat, nombre, precio, popularidad) in enumerate(CATALOGO, start=1):
            if nombre_cat not in categorias:
                categorias[nombre_cat], _ = Categoria.objects.get_or_create(nombre=nombre_cat)
            stock_minimo = max(3, popularidad)
            producto = crear_producto_con_stock_inicial(
                datos_producto={
                    "codigo_barras": codigo_ean13(indice),
                    "nombre": nombre,
                    "id_categoria": categorias[nombre_cat],
                    "precio": precio,
                    "stock_minimo": stock_minimo,
                },
                stock_inicial=popularidad * 6,
            )
            producto.popularidad = popularidad
            productos.append(producto)

        Producto.objects.filter(pk__in=[p.pk for p in productos]).update(
            fecha_creacion=fecha_alta
        )
        MovimientoStock.objects.filter(id_producto__in=productos).update(fecha_hora=fecha_alta)
        return productos

    def _horas_del_dia(self, dia, cantidad, ahora):
        horas = self.azar.choices(
            list(PESOS_HORA), weights=list(PESOS_HORA.values()), k=cantidad
        )
        fechas = sorted(
            self._fecha(dia, h, self.azar.randrange(60), self.azar.randrange(60))
            for h in horas
        )
        return [f for f in fechas if f < ahora]

    def _reponer_si_falta(self, producto, stock, necesario, fecha):
        """Simula que el almacenero repone antes de quedarse sin stock."""
        if stock[producto.pk] - necesario >= producto.stock_minimo:
            return
        cantidad = producto.popularidad * 6 + necesario
        registrar_entrada_stock(producto=producto, cantidad=cantidad)
        movimiento = MovimientoStock.objects.filter(id_producto=producto).latest("pk")
        MovimientoStock.objects.filter(pk=movimiento.pk).update(
            fecha_hora=fecha - timedelta(minutes=self.azar.randint(5, 90))
        )
        stock[producto.pk] += cantidad

    def _crear_ventas(
        self,
        *,
        productos,
        vendedores,
        admin,
        inicio,
        hoy,
        ventas_por_dia,
        caida_dias,
        caida_porcentaje,
    ):
        stock = {p.pk: p.stock_actual for p in productos}
        pesos = [p.popularidad for p in productos]
        medios, pesos_medios = zip(*MEDIOS_PAGO)
        ahora = timezone.now()
        inicio_caida = hoy - timedelta(days=caida_dias) if caida_dias else None
        total = 0

        dia = inicio
        while dia <= hoy:
            promedio = ventas_por_dia * (1.3 if dia.weekday() >= 5 else 1.0)
            if inicio_caida and dia > inicio_caida:
                promedio *= 1 - caida_porcentaje / 100
            cantidad = max(1, round(self.azar.gauss(promedio, promedio * 0.15)))

            for fecha in self._horas_del_dia(dia, cantidad, ahora):
                lineas = self.azar.choices([1, 2, 3, 4], weights=[45, 30, 15, 10])[0]
                elegidos = {
                    p.pk: p for p in self.azar.choices(productos, weights=pesos, k=lineas)
                }
                items = []
                for producto in elegidos.values():
                    unidades = self.azar.choices([1, 2, 3], weights=[75, 20, 5])[0]
                    self._reponer_si_falta(producto, stock, unidades, fecha)
                    items.append((producto.pk, unidades))

                venta = registrar_venta(
                    usuario=self.azar.choice(vendedores),
                    items=items,
                    medio_pago=self.azar.choices(medios, weights=pesos_medios)[0],
                )
                for id_producto, unidades in items:
                    stock[id_producto] -= unidades

                # Se anula antes de envejecer la venta: anular_venta exige estar en plazo.
                if self.azar.randrange(100) < PORCENTAJE_ANULADAS:
                    anular_venta(venta=venta, usuario=admin)
                    for id_producto, unidades in items:
                        stock[id_producto] += unidades
                    MovimientoStock.objects.filter(
                        id_venta=venta, tipo=TipoMovimiento.ENTRADA
                    ).update(fecha_hora=fecha + timedelta(minutes=self.azar.randint(1, 15)))

                Venta.objects.filter(pk=venta.pk).update(fecha_hora=fecha)
                MovimientoStock.objects.filter(
                    id_venta=venta, tipo=TipoMovimiento.SALIDA
                ).update(fecha_hora=fecha)
                total += 1

            dia += timedelta(days=1)

        return total
