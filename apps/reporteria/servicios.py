from django.db.models import OuterRef, Subquery
from django.db.models.functions import TruncTime

from apps.almacenes.models import ZONA_HORARIA_ALMACEN, FranjaHoraria, condicion_franja
from apps.inventario.models import MotivoAjuste, MovimientoStock, TipoMovimiento


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


def ajustes_de_exactitud(almacen):
    """
    Ajustes que cuentan para el indicador «exactitud de inventario» (§7): todos los
    movimientos tipo ajuste EXCEPTO los de «Alta rápida en caja», porque un producto
    que nace en el mesón no es una diferencia de inventario.
    """
    return (
        MovimientoStock.objects.del_almacen(almacen)
        .filter(tipo=TipoMovimiento.AJUSTE)
        .exclude(motivo=MotivoAjuste.ALTA_RAPIDA)
    )
