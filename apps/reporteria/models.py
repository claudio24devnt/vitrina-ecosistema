from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.almacenes.aislamiento import ModeloDeAlmacen


class AccesoReporte(ModeloDeAlmacen):
    """Cada consulta del reporte mensual (indicador «uso efectivo de la reportería»)."""

    id_acceso = models.BigAutoField(primary_key=True, db_column="id_acceso")
    id_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario",
        related_name="accesos_reporte",
        db_index=False,
    )
    mes_consultado = models.DateField(help_text="Primer día del mes consultado.")
    fecha_hora = models.DateTimeField(default=timezone.now, db_default=Now())

    class Meta:
        db_table = "acceso_reporte"
        default_manager_name = "sin_aislamiento"
        ordering = ["-fecha_hora"]
        verbose_name = "acceso a reporte"
        verbose_name_plural = "accesos a reportes"
        indexes = [
            models.Index(fields=["id_almacen", "fecha_hora"], name="ix_acceso_almacen_fecha")
        ]

    def __str__(self):
        return f"{self.id_usuario_id} consultó {self.mes_consultado:%Y-%m}"
