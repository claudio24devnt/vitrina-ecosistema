from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario

from .forms import CategoriaForm, NuevoProductoForm, ProductoForm
from .models import Categoria, Producto
from .servicios import (
    CodigoDuplicadoError,
    actualizar_producto,
    crear_categoria,
    registrar_producto,
)

solo_admin = rol_requerido(RolUsuario.ADMIN)


@login_required
def lista_productos(request):
    """Inventario: ambos roles lo consultan; sólo el administrador ve las acciones."""
    busqueda = request.GET.get("q", "").strip()
    solo_stock_bajo = request.GET.get("stock_bajo") == "1"
    productos = Producto.objects.del_almacen(request.almacen).select_related("id_categoria")
    if busqueda:
        productos = productos.filter(
            Q(nombre__icontains=busqueda) | Q(codigo_barras__icontains=busqueda)
        )
    if solo_stock_bajo:
        productos = productos.filter(stock_actual__lte=F("stock_minimo"))

    total_stock_bajo = (
        Producto.objects.del_almacen(request.almacen)
        .filter(stock_actual__lte=F("stock_minimo"))
        .count()
    )
    return render(
        request,
        "inventario/lista_productos.html",
        {
            "productos": productos,
            "busqueda": busqueda,
            "solo_stock_bajo": solo_stock_bajo,
            "total_stock_bajo": total_stock_bajo,
        },
    )


@solo_admin
def escanear(request):
    return render(
        request, "inventario/escanear.html", {"codigo": request.GET.get("codigo", "")}
    )


@solo_admin
def nuevo_producto(request):
    if request.method == "POST":
        form = NuevoProductoForm(request.POST, almacen=request.almacen)
        if form.is_valid():
            datos = form.cleaned_data
            try:
                producto = registrar_producto(
                    almacen=request.almacen,
                    usuario=request.user,
                    codigo_barras=datos["codigo_barras"],
                    nombre=datos["nombre"],
                    precio=datos["precio"],
                    categoria=datos["categoria"],
                    stock_minimo=datos["stock_minimo"],
                    stock_inicial=datos["stock_inicial"],
                )
            except CodigoDuplicadoError as error:
                # CU-01 2a: no se duplica; se lleva al usuario a sumar stock al existente.
                messages.warning(request, str(error))
                consulta = urlencode({"codigo": error.producto.codigo_barras})
                return redirect(f"{reverse('inventario:escanear')}?{consulta}")
            except ReglaDeNegocioError as error:
                form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    f"Producto «{producto.nombre}» registrado con "
                    f"{producto.stock_actual} unidades.",
                )
                return redirect("inventario:escanear")
    else:
        form = NuevoProductoForm(
            almacen=request.almacen, initial={"codigo_barras": request.GET.get("codigo", "")}
        )
    return render(request, "inventario/form_producto.html", {"form": form, "modo": "nuevo"})


@solo_admin
def editar_producto(request, id_producto):
    producto = get_object_or_404(Producto.objects.del_almacen(request.almacen), pk=id_producto)
    if request.method == "POST":
        form = ProductoForm(request.POST, almacen=request.almacen)
        if form.is_valid():
            datos = form.cleaned_data
            try:
                actualizar_producto(
                    almacen=request.almacen,
                    producto=producto,
                    codigo_barras=datos["codigo_barras"],
                    nombre=datos["nombre"],
                    precio=datos["precio"],
                    categoria=datos["categoria"],
                    stock_minimo=datos["stock_minimo"],
                )
            except ReglaDeNegocioError as error:
                form.add_error(None, str(error))
            else:
                messages.success(request, f"Producto «{producto.nombre}» actualizado.")
                return redirect("inventario:lista_productos")
    else:
        form = ProductoForm(
            almacen=request.almacen,
            initial={
                "codigo_barras": producto.codigo_barras,
                "nombre": producto.nombre,
                "categoria": producto.id_categoria_id,
                "precio": producto.precio,
                "stock_minimo": producto.stock_minimo,
            },
        )
    return render(
        request,
        "inventario/form_producto.html",
        {"form": form, "modo": "editar", "producto": producto},
    )


@solo_admin
def categorias(request):
    form = CategoriaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            categoria = crear_categoria(
                almacen=request.almacen, nombre=form.cleaned_data["nombre"]
            )
        except ReglaDeNegocioError as error:
            form.add_error("nombre", str(error))
        else:
            messages.success(request, f"Categoría «{categoria.nombre}» creada.")
            return redirect("inventario:categorias")
    return render(
        request,
        "inventario/categorias.html",
        {"form": form, "categorias": Categoria.objects.del_almacen(request.almacen)},
    )
