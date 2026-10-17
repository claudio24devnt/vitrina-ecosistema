from django.contrib import admin

from .models import AccesoReporte, Alerta


@admin.register(AccesoReporte)
class AccesoReporteAdmin(admin.ModelAdmin):
    list_display = ["id_acceso", "id_almacen", "id_usuario", "mes_consultado", "fecha_hora"]
    list_filter = ["id_almacen"]


@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ["id_alerta", "id_almacen", "tipo", "fecha_referencia", "fecha_vista"]
    list_filter = ["id_almacen", "tipo"]
