from django.contrib import admin

from .models import Categoria, MovimientoStock, Producto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ["id_categoria", "id_almacen", "nombre"]
    list_filter = ["id_almacen"]
    search_fields = ["nombre"]


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = [
        "id_producto",
        "id_almacen",
        "codigo_barras",
        "nombre",
        "id_categoria",
        "precio",
        "stock_actual",
        "stock_minimo",
    ]
    list_filter = ["id_almacen"]
    search_fields = ["nombre", "codigo_barras"]


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = [
        "id_movimiento",
        "id_producto",
        "tipo",
        "cantidad",
        "fecha_hora",
        "id_venta",
    ]
    list_filter = ["id_almacen", "tipo"]
    search_fields = ["id_producto__nombre", "id_producto__codigo_barras"]
    readonly_fields = ["fecha_hora"]
