"""
Prepara un almacén para la prueba de carga de la caja (§6: p95 < 2 s) en Azure.
DATOS FICTICIOS: los productos son los inventados de `cargar_datos_ficticios`; no
provienen del almacén piloto ni de ningún almacén real.

Antes, el operador crea en «Almacenes» un almacén con plan «carga» (y su
administrador). Este comando, que se corre una vez por SSH:

    python manage.py preparar_almacen_carga --rut <RUT del almacén de carga> \
        --nombre-vendedor "Vendedor Carga" --email-vendedor <correo>

agrega los 24 productos ficticios con stock alto (la carga no debe chocar con el
aviso de stock insuficiente) y un vendedor, cuya contraseña pide por teclado. Es
idempotente. Sólo actúa sobre almacenes de plan «carga»: la carga registra ventas
y nunca debe tocar el almacén piloto.
"""

import getpass
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.management.commands.cargar_datos_ficticios import CATALOGO
from apps.almacenes.models import Almacen
from apps.almacenes.servicios import normalizar_rut
from apps.inventario.models import Categoria, Producto
from apps.inventario.servicios import registrar_producto
from apps.usuarios.models import RolUsuario, Usuario
from apps.usuarios.servicios import crear_vendedor

PLAN_CARGA = "carga"
STOCK_CARGA = 100_000


def codigo_ficticio(indice):
    """Los mismos códigos que pruebas_carga/locustfile.py y cargar_datos_ficticios."""
    return f"20000000{indice:05d}"


class Command(BaseCommand):
    help = "Prepara un almacén de plan «carga» para la prueba Locust. Pide la contraseña."

    def add_arguments(self, parser):
        parser.add_argument("--rut", required=True, help="RUT del almacén de carga.")
        parser.add_argument("--nombre-vendedor", default="Vendedor Carga")
        parser.add_argument("--email-vendedor", required=True)

    def handle(self, *args, rut, nombre_vendedor, email_vendedor, **opciones):
        try:
            rut = normalizar_rut(rut)
        except ReglaDeNegocioError as error:
            raise CommandError(str(error)) from None
        # Transversal a propósito: el almacén se busca por RUT.
        almacen = Almacen.sin_aislamiento.filter(rut=rut).first()
        if almacen is None:
            raise CommandError("No hay un almacén con ese RUT. Créalo antes en «Almacenes».")
        if almacen.plan != PLAN_CARGA:
            raise CommandError(
                f"«{almacen.razon_social}» tiene plan «{almacen.plan}», no «{PLAN_CARGA}». "
                "La prueba de carga registra ventas: sólo se prepara un almacén de carga."
            )
        autor = Usuario.objects.del_almacen(almacen).filter(rol=RolUsuario.ADMIN).first()
        if autor is None:
            raise CommandError("El almacén de carga no tiene administrador.")

        nuevos = self._productos(almacen, autor)
        self.stdout.write(f"Productos ficticios nuevos: {nuevos} (de {len(CATALOGO)}).")

        email = email_vendedor.strip().lower()
        if Usuario.objects.del_almacen(almacen).filter(email__iexact=email).exists():
            self.stdout.write(f"El vendedor {email} ya existía.")
        else:
            clave = getpass.getpass("Contraseña del vendedor de carga: ")
            if clave != getpass.getpass("Repite la contraseña: "):
                raise CommandError("Las contraseñas no coinciden.")
            try:
                crear_vendedor(
                    almacen=almacen, nombre=nombre_vendedor, email=email, password=clave
                )
            except ReglaDeNegocioError as error:
                raise CommandError(str(error)) from None
            self.stdout.write(f"Vendedor {email} creado.")
        self.stdout.write(self.style.SUCCESS(f"«{almacen.razon_social}» listo para la carga."))

    @transaction.atomic
    def _productos(self, almacen, autor):
        existentes = set(
            Producto.objects.del_almacen(almacen).values_list("codigo_barras", flat=True)
        )
        nuevos = 0
        for indice, (categoria, nombre, precio, _minimo, _popularidad) in enumerate(CATALOGO):
            codigo = codigo_ficticio(indice)
            if codigo in existentes:
                continue
            categoria, _ = Categoria.objects.del_almacen(almacen).get_or_create(
                nombre=categoria
            )
            registrar_producto(
                almacen=almacen,
                usuario=autor,
                codigo_barras=codigo,
                nombre=nombre,
                precio=Decimal(precio),
                categoria=categoria,
                stock_minimo=0,
                stock_inicial=STOCK_CARGA,
            )
            nuevos += 1
        return nuevos
