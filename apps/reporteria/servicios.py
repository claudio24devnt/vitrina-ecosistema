from django.db.models import OuterRef, Subquery
from django.db.models.functions import TruncTime

from apps.almacenes.models import ZONA_HORARIA_ALMACEN, FranjaHoraria, condicion_franja


def hora_local(campo):
    """`(campo AT TIME ZONE 'America/Santiago')::time`: hora de reloj del almacén."""
    return TruncTime(campo, tzinfo=ZONA_HORARIA_ALMACEN)


def anotar_franja(ventas, almacen):
    """
    Agrega `franja` (nombre) y `franja_orden` a un queryset de ventas, calculados en
    PostgreSQL. La comparación se hace en hora local, nunca en UTC.
    """
    ventas = ventas.annotate(hora_local=hora_local("fecha_hora"))
    franjas = FranjaHoraria.objects.del_almacen(almacen).filter(
        condicion_franja(OuterRef("hora_local"))
    )
    return ventas.annotate(
        franja=Subquery(franjas.values("nombre")[:1]),
        franja_orden=Subquery(franjas.values("orden")[:1]),
    )
