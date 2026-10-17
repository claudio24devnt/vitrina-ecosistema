from django.conf import settings
from django.db import models
from django.db.models import Q
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


class TipoAlerta(models.TextChoices):
    STOCK_BAJO = "stock_bajo", "Stock bajo"
    CIERRE_MES = "cierre_mes", "Cierre de mes"


class Alerta(ModeloDeAlmacen):
    """
    Aviso para el panel del administrador (aprobado el 2026-10-16). Lo crean los
    comandos programados (CU-05 y cierre de mes); la alerta sólo avisa, no guarda el
    detalle: la lista de productos o el reporte se calculan al abrirlos.
    `fecha_referencia` es el día revisado (stock bajo) o el primer día del mes cerrado
    (cierre de mes); con el tipo forma la clave que hace idempotentes a los comandos.
    """

    id_alerta = models.BigAutoField(primary_key=True, db_column="id_alerta")
    tipo = models.CharField(max_length=20, choices=TipoAlerta.choices)
    fecha_referencia = models.DateField()
    mensaje = models.CharField(max_length=200)
    fecha_hora = models.DateTimeField(default=timezone.now, db_default=Now())
    fecha_vista = models.DateTimeField(null=True, blank=True)
    id_usuario_vista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="id_usuario_vista",
        related_name="alertas_vistas",
        null=True,
        blank=True,
        db_index=False,
    )

    class Meta:
        db_table = "alerta"
        default_manager_name = "sin_aislamiento"
        ordering = ["-fecha_hora"]
        verbose_name = "alerta"
        verbose_name_plural = "alertas"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoAlerta.values), name="ck_alerta_tipo"
            ),
            # Vista <=> se sabe quién y cuándo.
            models.CheckConstraint(
                condition=Q(fecha_vista__isnull=True, id_usuario_vista__isnull=True)
                | Q(fecha_vista__isnull=False, id_usuario_vista__isnull=False),
                name="ck_alerta_vista_coherente",
            ),
            models.UniqueConstraint(
                fields=["id_almacen", "tipo", "fecha_referencia"], name="uq_alerta"
            ),
        ]
        indexes = [
            models.Index(
                fields=["id_almacen", "fecha_hora"],
                name="ix_alerta_pendientes",
                condition=Q(fecha_vista__isnull=True),
            )
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.fecha_referencia:%Y-%m-%d}"
