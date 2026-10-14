from datetime import datetime, timedelta

from django.utils import timezone

from apps.almacenes.models import ZONA_HORARIA_ALMACEN

# El registro y la anulación transaccional de ventas se implementan en el paquete 1.4.3.


def limite_anulacion(venta):
    """
    Último instante (exclusivo) en que la venta se puede anular: el minuto
    `hora_limite_anulacion` del día de la venta, en hora local del almacén, incluido
    completo. Con el valor por defecto 23:59, se puede anular hasta las 23:59:59.

    Limitación declarada: un almacén que cierra después de medianoche no queda bien
    modelado; una venta de la 01:30 pertenece al día calendario en que ocurrió.
    """
    dia_local = timezone.localtime(venta.fecha_hora, ZONA_HORARIA_ALMACEN).date()
    hora_limite = venta.id_almacen.hora_limite_anulacion
    return datetime.combine(dia_local, hora_limite, tzinfo=ZONA_HORARIA_ALMACEN) + timedelta(
        minutes=1
    )


def anulacion_en_plazo(venta, momento=None):
    momento = momento or timezone.now()
    return momento < limite_anulacion(venta)
