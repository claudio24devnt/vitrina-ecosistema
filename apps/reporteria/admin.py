from django.contrib import admin

from .models import AccesoReporte


@admin.register(AccesoReporte)
class AccesoReporteAdmin(admin.ModelAdmin):
    list_display = ["id_acceso", "id_almacen", "id_usuario", "mes_consultado", "fecha_hora"]
    list_filter = ["id_almacen"]
