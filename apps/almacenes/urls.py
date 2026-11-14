from django.urls import path

from . import views

app_name = "almacenes"

urlpatterns = [
    path("almacenes/", views.plataforma_almacenes, name="plataforma"),
    path(
        "administradores/<int:id_usuario>/contrasena/",
        views.contrasena_administrador,
        name="contrasena_administrador",
    ),
]
