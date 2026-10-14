from django.contrib import admin

from .models import DetalleVenta, Venta


class DetalleVentaInline(admin.TabularInline):
    model = DetalleVenta
    extra = 0
    readonly_fields = ["subtotal"]


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ["id_venta", "id_usuario", "fecha_hora", "total", "medio_pago", "estado"]
    list_filter = ["estado", "medio_pago"]
    readonly_fields = ["fecha_hora"]
    inlines = [DetalleVentaInline]
