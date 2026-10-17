"""
Crea el operador de la plataforma: el usuario que da de alta almacenes en
/plataforma/almacenes/. Se corre una vez por entorno (en Azure, por SSH):

    python manage.py crear_operador --nombre "..." --email ... --rut 76.123.456-7

La contraseña se pide por teclado, sin mostrarla; nunca va como argumento, para que
no quede en el historial de la terminal.

El modelo exige que todo usuario pertenezca a un almacén, así que el operador vive
en un almacén «de operación» (plan PLAN_OPERACION), que no aparece entre los
clientes. Si ya existe, se reutiliza.
"""

import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import Almacen
from apps.almacenes.servicios import PLAN_OPERACION, crear_almacen, normalizar_rut
from apps.usuarios.servicios import crear_administrador


class Command(BaseCommand):
    help = "Crea el operador de la plataforma (alta de almacenes). Pide la contraseña."

    def add_arguments(self, parser):
        parser.add_argument("--nombre", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--rut", required=True, help="RUT de quien opera la plataforma (para su almacén)."
        )
        parser.add_argument("--razon-social", default="TivoScanea (operación)")

    def _pedir_clave(self):
        clave = getpass.getpass("Contraseña del operador: ")
        if clave != getpass.getpass("Repite la contraseña: "):
            raise CommandError("Las contraseñas no coinciden.")
        return clave

    def handle(self, *args, nombre, email, rut, razon_social, **opciones):
        try:
            rut = normalizar_rut(rut)
        except ReglaDeNegocioError as error:
            raise CommandError(str(error)) from None
        clave = self._pedir_clave()
        try:
            with transaction.atomic():
                # Transversal a propósito: se busca el almacén de operación, si existe.
                almacen = Almacen.sin_aislamiento.filter(plan=PLAN_OPERACION).first()
                if almacen is None:
                    almacen = crear_almacen(
                        razon_social=razon_social, rut=rut, plan=PLAN_OPERACION
                    )
                operador = crear_administrador(
                    almacen=almacen, nombre=nombre, email=email, password=clave, operador=True
                )
        except ReglaDeNegocioError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(
            self.style.SUCCESS(
                f"Operador {operador.email} creado. Entra y ve a «Almacenes» en el menú."
            )
        )
