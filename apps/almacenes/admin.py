from django.contrib import admin

from .models import Almacen, FranjaHoraria


class FranjaHorariaInline(admin.TabularInline):
    model = FranjaHoraria
    extra = 0
    fk_name = "id_almacen"


@admin.register(Almacen)
class AlmacenAdmin(admin.ModelAdmin):
    list_display = ["id_almacen", "razon_social", "rut", "plan", "activo", "fecha_alta"]
    list_filter = ["activo", "plan"]
    search_fields = ["razon_social", "rut"]
    inlines = [FranjaHorariaInline]
