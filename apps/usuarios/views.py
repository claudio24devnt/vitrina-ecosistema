from django.contrib import messages
from django.shortcuts import redirect, render

from apps.almacenes.errores import ReglaDeNegocioError

from .decorators import rol_requerido
from .forms import VendedorForm
from .models import RolUsuario
from .servicios import crear_vendedor, vendedores_del_almacen


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
