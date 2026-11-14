from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="usuarios/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("vendedores/", views.vendedores, name="vendedores"),
    path(
        "vendedores/<int:id_usuario>/contrasena/",
        views.contrasena_vendedor,
        name="contrasena_vendedor",
    ),
    path(
        "vendedores/<int:id_usuario>/eliminar/",
        views.confirmar_eliminar_vendedor,
        name="eliminar_vendedor",
    ),
    path(
        "vendedores/<int:id_usuario>/estado/",
        views.estado_vendedor,
        name="estado_vendedor",
    ),
    path("contrasena/", views.CambiarContrasenaView.as_view(), name="cambiar_contrasena"),
    # Recuperación por correo (fase 2). El enlace del correo lleva uidb64 y token.
    path("recuperar/", views.RecuperarContrasenaView.as_view(), name="recuperar"),
    path("recuperar/enviado/", views.RecuperarEnviadoView.as_view(), name="recuperar_enviado"),
    path(
        "recuperar/<uidb64>/<token>/",
        views.RecuperarConfirmarView.as_view(),
        name="recuperar_confirmar",
    ),
    path("recuperar/listo/", views.RecuperarListoView.as_view(), name="recuperar_listo"),
]
