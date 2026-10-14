from django.urls import path

from . import views

app_name = "ventas"

urlpatterns = [
    path("", views.punto_venta, name="punto_venta"),
    path("historial/", views.lista_ventas, name="lista_ventas"),
    path("<int:id_venta>/", views.detalle_venta, name="detalle_venta"),
    path("<int:id_venta>/anular/", views.anular, name="anular"),
]
