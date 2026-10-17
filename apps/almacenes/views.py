from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.inventario.models import Producto
from apps.inventario.servicios import productos_con_stock_bajo
from apps.reporteria.servicios import alertas_del_panel
from apps.usuarios.decorators import operador_requerido

from .errores import ReglaDeNegocioError
from .formularios import AltaAlmacenForm
from .servicios import alta_almacen, almacenes_clientes


@login_required
def inicio(request):
    return render(
        request,
        "inicio.html",
        {
            "total_productos": Producto.objects.del_almacen(request.almacen).count(),
            "total_stock_bajo": productos_con_stock_bajo(request.almacen).count(),
            # Las alertas son del administrador (CU-05 y cierre de mes).
            "alertas": alertas_del_panel(request.almacen) if request.user.es_admin else [],
        },
    )


@operador_requerido
def plataforma_almacenes(request):
    """Lista de almacenes clientes y alta de uno nuevo con su administrador."""
    form = AltaAlmacenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        try:
            almacen, administrador = alta_almacen(
                razon_social=datos["razon_social"],
                rut=datos["rut"],
                plan=datos["plan"],
                direccion=datos["direccion"],
                nombre_admin=datos["nombre_admin"],
                email_admin=datos["email_admin"],
                password_admin=datos["password"],
            )
        except ReglaDeNegocioError as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Almacén «{almacen.razon_social}» creado. Su administrador ya puede "
                f"iniciar sesión con {administrador.email}.",
            )
            return redirect("almacenes:plataforma")
    return render(
        request,
        "almacenes/plataforma.html",
        {"form": form, "almacenes": almacenes_clientes()},
    )
