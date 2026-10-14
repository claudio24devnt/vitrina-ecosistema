from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now
from django.utils import timezone

from .aislamiento import ModeloAislado, ModeloDeAlmacen

# Todas las horas de reloj de pared (plazo de anulación, franjas del reporte) se
# interpretan en esta zona. Limitación declarada: un almacén de Magallanes
# (America/Punta_Arenas, sin horario de invierno) queda desfasado una hora en invierno.
ZONA_HORARIA_ALMACEN = ZoneInfo("America/Santiago")


class Almacen(ModeloAislado):
    id_almacen = models.BigAutoField(primary_key=True, db_column="id_almacen")
    razon_social = models.CharField(max_length=120)
    rut = models.CharField(max_length=12)
    direccion = models.CharField(max_length=200, null=True, blank=True)
    plan = models.CharField(max_length=20)
    fecha_alta = models.DateTimeField(default=timezone.now, db_default=Now())
    activo = models.BooleanField(default=True, db_default=True)
    # Plazo para anular ventas: hasta esta hora (inclusive el minuto) del día de la venta.
    # No es el horario de cierre del local.
    hora_limite_anulacion = models.TimeField(default=time(23, 59), db_default=time(23, 59))

    class Meta:
        db_table = "almacen"
        default_manager_name = "sin_aislamiento"
        verbose_name = "almacén"
        verbose_name_plural = "almacenes"
        constraints = [models.UniqueConstraint(fields=["rut"], name="uq_almacen_rut")]

    def __str__(self):
        return self.razon_social


class FranjaHoraria(ModeloDeAlmacen):
    """
    Banda horaria del reporte mensual. `hora_fin` es EXCLUSIVA: la franja cubre
    [hora_inicio, hora_fin). Si hora_inicio > hora_fin la franja cruza la medianoche.
    """

    id_franja = models.BigAutoField(primary_key=True, db_column="id_franja")
    nombre = models.CharField(max_length=20)
    orden = models.SmallIntegerField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    class Meta:
        db_table = "franja_horaria"
        default_manager_name = "sin_aislamiento"
        ordering = ["orden"]
        verbose_name = "franja horaria"
        verbose_name_plural = "franjas horarias"
        constraints = [
            models.UniqueConstraint(
                fields=["id_almacen", "nombre"], name="uq_franja_almacen_nombre"
            ),
            models.UniqueConstraint(
                fields=["id_almacen", "orden"], name="uq_franja_almacen_orden"
            ),
        ]
        indexes = [models.Index(fields=["id_almacen", "orden"], name="ix_franja_almacen")]

    def __str__(self):
        return f"{self.nombre} ({self.etiqueta})"

    @property
    def cruza_medianoche(self):
        return self.hora_inicio > self.hora_fin

    @property
    def etiqueta(self):
        """«07:00 – 10:59»: el límite superior mostrado es hora_fin menos un minuto."""
        ultimo_minuto = datetime.combine(date(2000, 1, 2), self.hora_fin) - timedelta(
            minutes=1
        )
        return f"{self.hora_inicio:%H:%M} – {ultimo_minuto:%H:%M}"


def condicion_franja(hora):
    """
    Q que selecciona la(s) franja(s) que contienen `hora` (expresión o valor TIME).
    Cubre las franjas que cruzan la medianoche, que un BETWEEN dejaría vacías.
    """
    normal = Q(hora_inicio__lt=models.F("hora_fin"), hora_inicio__lte=hora, hora_fin__gt=hora)
    cruza = Q(hora_inicio__gt=models.F("hora_fin")) & (
        Q(hora_inicio__lte=hora) | Q(hora_fin__gt=hora)
    )
    return normal | cruza
