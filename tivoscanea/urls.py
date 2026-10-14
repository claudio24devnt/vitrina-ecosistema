from django.contrib import admin
from django.urls import include, path

from apps.almacenes.views import inicio
from apps.inventario.urls import api_urlpatterns as inventario_api

urlpatterns = [
    path("", inicio, name="inicio"),
    path("admin/", admin.site.urls),
    path("cuentas/", include("apps.usuarios.urls")),
    path("productos/", include("apps.inventario.urls")),
    path("api/", include((inventario_api, "api"))),
]
