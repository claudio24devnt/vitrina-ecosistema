from django.urls import path

from . import views

app_name = "almacenes"

urlpatterns = [
    path("almacenes/", views.plataforma_almacenes, name="plataforma"),
]
