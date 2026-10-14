from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuentas/", include("apps.usuarios.urls")),
    path("ventas/", include("apps.ventas.urls")),
    path("", include("apps.inventario.urls")),
]
