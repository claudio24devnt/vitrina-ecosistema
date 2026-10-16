from django.urls import path

from . import api, views

app_name = "ventas"

urlpatterns = [
    path("", views.ventas_del_dia, name="ventas_del_dia"),
    path("caja/", views.caja, name="caja"),
    path("<int:id_venta>/", views.comprobante, name="comprobante"),
    path("<int:id_venta>/anular/", views.anular, name="anular"),
]

# Se montan bajo /api/ con el namespace "api" (ver tivoscanea/urls.py).
api_urlpatterns = [
    path("ventas/", api.RegistrarVentaAPI.as_view(), name="registrar_venta"),
    path("productos/alta-rapida/", api.AltaRapidaAPI.as_view(), name="alta_rapida"),
]
