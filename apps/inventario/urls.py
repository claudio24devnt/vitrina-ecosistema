from django.urls import path

from . import api, views

app_name = "inventario"

urlpatterns = [
    path("", views.lista_productos, name="lista_productos"),
    path("escanear/", views.escanear, name="escanear"),
    path("nuevo/", views.nuevo_producto, name="nuevo_producto"),
    path("<int:id_producto>/editar/", views.editar_producto, name="editar_producto"),
    path("<int:id_producto>/ajustar/", views.ajustar_inventario, name="ajustar"),
    path("categorias/", views.categorias, name="categorias"),
]

# Se montan bajo /api/ con el namespace "api" (ver tivoscanea/urls.py).
api_urlpatterns = [
    path(
        "productos/codigo/<str:codigo>/",
        api.ProductoPorCodigoAPI.as_view(),
        name="producto_por_codigo",
    ),
    path(
        "productos/<int:id_producto>/entradas/",
        api.EntradaStockAPI.as_view(),
        name="entrada_stock",
    ),
]
