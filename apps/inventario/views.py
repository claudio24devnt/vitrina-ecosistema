from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario

from .forms import (
    AjusteInventarioForm,
    CategoriaForm,
    FiltroInventarioForm,
    NuevoProductoForm,
    ProductoForm,
)
from .models import Categoria, Producto
from .servicios import (
    CodigoDuplicadoError,
    actualizar_producto,
    crear_categoria,
    filtrar_productos,
    productos_con_stock_bajo,
    registrar_ajuste_por_conteo,
    registrar_producto,
)

solo_admin = rol_requerido(RolUsuario.ADMIN)

# Filas por página del inventario: la lista no crece sin límite con el catálogo.
PRODUCTOS_POR_PAGINA = 50


@login_required
def lista_productos(request):
    """
    Inventario: ambos roles lo consultan; sólo el administrador ve las acciones. La
    búsqueda y los filtros los decide `filtrar_productos`; la vista sólo los lee del GET.
    """
    datos = request.GET.copy()
    # Enlaces antiguos del panel y marcadores: «?stock_bajo=1» es «?stock=bajo».
    if datos.pop("stock_bajo", None) == ["1"] and not datos.get("stock"):
        datos["stock"] = "bajo"
    filtro = FiltroInventarioForm(datos, almacen=request.almacen)
    criterios = filtro.criterios()
    # «?costo=sin» llega desde el reporte (completar costos). El vendedor no ve costos.
    sin_costo = request.user.es_admin and datos.get("costo") == "sin"
    productos = filtrar_productos(request.almacen, sin_costo=sin_costo, **criterios)

    total_stock_bajo = productos_con_stock_bajo(request.almacen).count()
    pagina = Paginator(productos, PRODUCTOS_POR_PAGINA).get_page(datos.get("pagina"))
    # Los enlaces de página conservan la búsqueda, los filtros y el orden.
    datos.pop("pagina", None)
    hay_filtros = bool(
        criterios["texto"] or criterios["categoria"] or criterios["stock"] != "todos"
    )
    return render(
        request,
        "inventario/lista_productos.html",
        {
            "productos": pagina.object_list,
            "pagina": pagina,
            "filtros": datos.urlencode(),
            "filtro": filtro,
            "hay_filtros": hay_filtros or sin_costo,
            "sin_costo": sin_costo,
            "solo_stock_bajo": criterios["stock"] == "bajo",
            "total_stock_bajo": total_stock_bajo,
        },
    )


def _aviso_categoria(producto, datos):
    """Texto extra del mensaje de éxito cuando se escribió una categoría nueva."""
    if not (datos.get("categoria_nueva") or "").strip() or producto.id_categoria is None:
        return ""
    nombre = producto.id_categoria.nombre
    if producto.categoria_creada:
        return f" Se creó la categoría «{nombre}»."
    return f" La categoría «{nombre}» ya existía y se usó esa."


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
                    categoria_nueva=datos["categoria_nueva"],
                    stock_minimo=datos["stock_minimo"],
                    stock_inicial=datos["stock_inicial"],
                    descripcion=datos["descripcion"],
                    contenido=datos["contenido"],
                    unidad_contenido=datos["unidad_contenido"],
                    costo=datos["costo"],
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
                    f"{producto.stock_actual} unidades.{_aviso_categoria(producto, datos)}",
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
                    categoria_nueva=datos["categoria_nueva"],
                    stock_minimo=datos["stock_minimo"],
                    descripcion=datos["descripcion"],
                    contenido=datos["contenido"],
                    unidad_contenido=datos["unidad_contenido"],
                    costo=datos["costo"],
                )
            except ReglaDeNegocioError as error:
                form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    f"Producto «{producto.nombre}» actualizado."
                    f"{_aviso_categoria(producto, datos)}",
                )
                return redirect("inventario:lista_productos")
    else:
        form = ProductoForm(
            almacen=request.almacen,
            initial={
                "codigo_barras": producto.codigo_barras,
                "nombre": producto.nombre,
                "categoria": producto.id_categoria_id,
                "precio": producto.precio,
                "costo": producto.costo,
                "stock_minimo": producto.stock_minimo,
                "descripcion": producto.descripcion or "",
                "contenido": producto.contenido_cifra,
                "unidad_contenido": producto.unidad_contenido or "",
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


@solo_admin
def ajustar_inventario(request, id_producto):
    """Ajuste por conteo: registra la diferencia (positiva o negativa) con motivo."""
    producto = get_object_or_404(Producto.objects.del_almacen(request.almacen), pk=id_producto)
    form = AjusteInventarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            movimiento = registrar_ajuste_por_conteo(
                almacen=request.almacen,
                producto=producto,
                cantidad_contada=form.cleaned_data["cantidad_contada"],
                motivo=form.cleaned_data["motivo"],
                usuario=request.user,
            )
        except ReglaDeNegocioError as error:
            form.add_error(None, str(error))
        else:
            signo = "+" if movimiento.cantidad > 0 else ""
            messages.success(
                request,
                f"Inventario de «{producto.nombre}» ajustado ({signo}{movimiento.cantidad}). "
                f"Stock actual: {producto.stock_actual}.",
            )
            return redirect("inventario:lista_productos")
    return render(request, "inventario/ajustar.html", {"form": form, "producto": producto})
