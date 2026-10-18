from django.urls import path

from . import api, views

app_name = "reporteria"

urlpatterns = [
    path("mensual/", views.reporte_mensual, name="reporte_mensual"),
    path("indicadores/", views.indicadores_del_mes, name="indicadores"),
    path("alertas/<int:id_alerta>/vista/", views.marcar_vista, name="marcar_vista"),
]

# Se montan bajo /api/ con el namespace "api" (ver tivoscanea/urls.py).
api_urlpatterns = [
    path("reportes/mensual/", api.ReporteMensualAPI.as_view(), name="reporte_mensual"),
]
