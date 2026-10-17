from django.contrib import admin
from django.urls import include, path

from apps.almacenes.views import inicio
from apps.inventario.urls import api_urlpatterns as inventario_api
from apps.reporteria.urls import api_urlpatterns as reporteria_api
from apps.ventas.urls import api_urlpatterns as ventas_api

urlpatterns = [
    path("", inicio, name="inicio"),
    path("admin/", admin.site.urls),
    path("cuentas/", include("apps.usuarios.urls")),
    path("productos/", include("apps.inventario.urls")),
    path("ventas/", include("apps.ventas.urls")),
    path("reportes/", include("apps.reporteria.urls")),
    path("api/", include((inventario_api + ventas_api + reporteria_api, "api"))),
]
