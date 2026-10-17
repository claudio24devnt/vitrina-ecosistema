from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.almacenes.models import Almacen
from apps.reporteria.servicios import hoy_local


class ComandoPorAlmacen(BaseCommand):
    """
    Base de los comandos programados (sin Celery: los invoca el scheduler del App
    Service, ver 1.6). Recorren los almacenes activos y son idempotentes: correrlos
    dos veces el mismo día no duplica alertas.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            help="Fecha de referencia AAAA-MM-DD (por omisión, hoy en hora de Santiago).",
        )

    def fecha(self, opciones):
        if not opciones["fecha"]:
            return hoy_local()
        try:
            return date.fromisoformat(opciones["fecha"])
        except ValueError as error:
            raise CommandError("La fecha debe tener el formato AAAA-MM-DD.") from error

    def almacenes(self):
        # Transversal a propósito: el comando atiende a todos los almacenes, y cada
        # consulta posterior se fija al almacén con del_almacen().
        return Almacen.sin_aislamiento.filter(activo=True).order_by("pk")
