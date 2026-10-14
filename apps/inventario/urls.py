from django.urls import path

from . import views

app_name = "inventario"

urlpatterns = [
    path("", views.lista_productos, name="lista_productos"),
    path("productos/nuevo/", views.crear_producto, name="crear_producto"),
    path("productos/<int:id_producto>/editar/", views.editar_producto, name="editar_producto"),
    path(
        "productos/<int:id_producto>/eliminar/",
        views.eliminar_producto,
        name="eliminar_producto",
    ),
    path("productos/<int:id_producto>/sumar-stock/", views.sumar_stock, name="sumar_stock"),
    path("escanear/", views.escaneo, name="escaneo"),
    path("escanear/buscar/", views.buscar_por_codigo, name="buscar_por_codigo"),
    path("categorias/", views.lista_categorias, name="lista_categorias"),
    path(
        "categorias/<int:id_categoria>/eliminar/",
        views.eliminar_categoria,
        name="eliminar_categoria",
    ),
]
