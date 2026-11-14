import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from apps.almacenes.errores import ReglaDeNegocioError

from .decorators import rol_requerido
from .forms import (
    CambioContrasenaForm,
    ContrasenaNuevaForm,
    ContrasenaRecuperadaForm,
    RecuperarContrasenaForm,
    VendedorForm,
)
from .models import RolUsuario, Usuario
from .servicios import (
    admitir_correo_de_recuperacion,
    crear_vendedor,
    puede_restablecer,
    restablecer_contrasena,
    vendedores_del_almacen,
)


@rol_requerido(RolUsuario.ADMIN)
def vendedores(request):
    form = VendedorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        try:
            vendedor = crear_vendedor(
                almacen=request.almacen,
                nombre=datos["nombre"],
                email=datos["email"],
                password=datos["password"],
            )
        except ReglaDeNegocioError as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Vendedor «{vendedor.nombre}» creado. Ya puede iniciar sesión con "
                f"{vendedor.email}.",
            )
            return redirect("usuarios:vendedores")
    return render(
        request,
        "usuarios/vendedores.html",
        {"form": form, "vendedores": vendedores_del_almacen(request.almacen)},
    )


def asignar_contrasena(request, usuario, volver_a):
    """
    Pantalla común para asignar una contraseña nueva a otro usuario (vendedor por su
    administrador, administrador por el operador). Quien llama ya validó el acceso.
    """
    if not puede_restablecer(request.user, usuario):
        raise Http404
    form = ContrasenaNuevaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            restablecer_contrasena(
                autor=request.user, usuario=usuario, password=form.cleaned_data["password"]
            )
        except ReglaDeNegocioError as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Contraseña de «{usuario.nombre}» cambiada. Entrégasela en persona; "
                "si tenía la sesión abierta, tendrá que ingresar de nuevo.",
            )
            return redirect(volver_a)
    return render(
        request,
        "usuarios/asignar_contrasena.html",
        {"form": form, "usuario_objetivo": usuario, "volver_a": volver_a},
    )


@rol_requerido(RolUsuario.ADMIN)
def contrasena_vendedor(request, id_usuario):
    """El administrador asigna una contraseña nueva a un vendedor de su almacén."""
    vendedor = get_object_or_404(
        Usuario.objects.del_almacen(request.almacen).filter(rol=RolUsuario.VENDEDOR),
        pk=id_usuario,
    )
    return asignar_contrasena(request, vendedor, "usuarios:vendedores")


class CambiarContrasenaView(auth_views.PasswordChangeView):
    """Cualquier usuario cambia su propia contraseña dando la actual."""

    form_class = CambioContrasenaForm
    template_name = "usuarios/cambiar_contrasena.html"
    success_url = reverse_lazy("inicio")

    def form_valid(self, form):
        respuesta = super().form_valid(form)  # mantiene esta sesión abierta
        messages.success(self.request, "Tu contraseña quedó cambiada.")
        return respuesta


class RecuperarContrasenaView(auth_views.PasswordResetView):
    """
    «¿Olvidaste tu contraseña?». Con correo configurado envía un enlace de un solo
    uso que vence en una hora; sin correo, explica a quién pedírsela. Nunca dice si
    el correo está registrado (la respuesta es la misma).
    """

    form_class = RecuperarContrasenaForm
    template_name = "usuarios/recuperar.html"
    email_template_name = "usuarios/correo_recuperar.txt"
    # Versión HTML con un botón: en texto plano, que el enlace se pueda abrir depende
    # del programa de correo. El texto plano se mantiene para los que no muestran HTML.
    html_email_template_name = "usuarios/correo_recuperar.html"
    subject_template_name = "usuarios/correo_recuperar_asunto.txt"
    success_url = reverse_lazy("usuarios:recuperar_enviado")

    def dispatch(self, request, *args, **kwargs):
        if not settings.RECUPERACION_POR_CORREO:
            return render(request, "usuarios/recuperar.html", {"sin_correo": True})
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        if admitir_correo_de_recuperacion(form.cleaned_data["email"]):
            try:
                return super().form_valid(form)
            except Exception:
                # Si el envío falla, se responde igual: un error sólo para los correos
                # registrados revelaría cuáles existen. Queda en el log.
                logging.getLogger("tivoscanea.correo").exception(
                    "No se pudo enviar el correo de recuperación"
                )
        # Tope alcanzado o envío fallido: misma respuesta que siempre.
        return redirect(self.success_url)


class RecuperarEnviadoView(auth_views.PasswordResetDoneView):
    template_name = "usuarios/recuperar_enviado.html"


class RecuperarConfirmarView(auth_views.PasswordResetConfirmView):
    form_class = ContrasenaRecuperadaForm
    template_name = "usuarios/recuperar_confirmar.html"
    success_url = reverse_lazy("usuarios:recuperar_listo")


class RecuperarListoView(auth_views.PasswordResetCompleteView):
    template_name = "usuarios/recuperar_listo.html"
