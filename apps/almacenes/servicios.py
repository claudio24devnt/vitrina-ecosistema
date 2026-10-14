from datetime import time

from django.db import transaction

from .models import Almacen, FranjaHoraria

# Franjas horarias iniciales del reporte mensual. SUPUESTO, no medición: son el valor
# de partida declarado en el informe, no datos del almacén piloto, y cada almacén las
# puede ajustar a su horario. hora_fin es exclusiva (ver FranjaHoraria).
FRANJAS_INICIALES = [
    ("Mañana", 1, time(7, 0), time(11, 0)),
    ("Mediodía", 2, time(11, 0), time(14, 0)),
    ("Tarde", 3, time(14, 0), time(18, 0)),
    ("Noche", 4, time(18, 0), time(22, 0)),
    ("Resto", 5, time(22, 0), time(7, 0)),
]


@transaction.atomic
def crear_almacen(*, razon_social, rut, plan, direccion=None) -> Almacen:
    """Crea el almacén junto con sus franjas horarias iniciales, en una sola transacción."""
    almacen = Almacen.objects.create(
        razon_social=razon_social, rut=rut, plan=plan, direccion=direccion
    )
    FranjaHoraria.objects.bulk_create(
        FranjaHoraria(
            id_almacen=almacen, nombre=nombre, orden=orden, hora_inicio=inicio, hora_fin=fin
        )
        for nombre, orden, inicio, fin in FRANJAS_INICIALES
    )
    return almacen
