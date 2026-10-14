from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, ProtectedError, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import CategoriaForm, NuevoProductoForm, ProductoForm, SumarStockForm
from .models import Categoria, Producto
from .services import crear_producto_con_stock_inicial, registrar_entrada_stock


@login_required
def lista_productos(request):
    query = request.GET.get("q", "").strip()
    productos = Producto.objects.select_related("id_categoria").all()
    if query:
        productos = productos.filter(
            Q(nombre__icontains=query) | Q(codigo_barras__icontains=query)
        )

    total_stock_bajo = Producto.objects.filter(stock_actual__lte=F("stock_minimo")).count()

    return render(
        request,
        "inventario/lista_productos.html",
        {
            "productos": productos,
            "query": query,
            "total_stock_bajo": total_stock_bajo,
        },
    )


@login_required
def crear_producto(request):
    codigo_inicial = request.GET.get("codigo", "")
    if request.method == "POST":
        form = NuevoProductoForm(request.POST)
        if form.is_valid():
            datos = {
                "codigo_barras": form.cleaned_data["codigo_barras"],
                "nombre": form.cleaned_data["nombre"],
                "id_categoria": form.cleaned_data["id_categoria"],
                "precio": form.cleaned_data["precio"],
                "stock_minimo": form.cleaned_data["stock_minimo"],
            }
            producto = crear_producto_con_stock_inicial(
                datos_producto=datos,
                stock_inicial=form.cleaned_data["stock_inicial"],
            )
            messages.success(request, f"Producto «{producto.nombre}» creado.")
            return redirect("inventario:lista_productos")
    else:
        form = NuevoProductoForm(initial={"codigo_barras": codigo_inicial})

    return render(request, "inventario/form_producto.html", {"form": form, "modo": "crear"})


@login_required
def editar_producto(request, id_producto):
    producto = get_object_or_404(Producto, pk=id_producto)
    if request.method == "POST":
        form = ProductoForm(request.POST, instance=producto)
        if form.is_valid():
            form.save()
            messages.success(request, f"Producto «{producto.nombre}» actualizado.")
            return redirect("inventario:lista_productos")
    else:
        form = ProductoForm(instance=producto)

    return render(
        request,
        "inventario/form_producto.html",
        {"form": form, "modo": "editar", "producto": producto},
    )


@require_POST
@login_required
def eliminar_producto(request, id_producto):
    producto = get_object_or_404(Producto, pk=id_producto)
    nombre = producto.nombre
    try:
        producto.delete()
        messages.success(request, f"Producto «{nombre}» eliminado.")
    except ProtectedError:
        messages.error(
            request,
            f"No se puede eliminar «{nombre}»: tiene movimientos de stock o "
            "ventas asociadas. Poné el stock en 0 si ya no se vende.",
        )
    return redirect("inventario:lista_productos")


@require_POST
@login_required
def sumar_stock(request, id_producto):
    producto = get_object_or_404(Producto, pk=id_producto)
    form = SumarStockForm(request.POST)
    if form.is_valid():
        registrar_entrada_stock(producto=producto, cantidad=form.cleaned_data["cantidad"])
        messages.success(
            request,
            f"Se agregaron {form.cleaned_data['cantidad']} unidades a «{producto.nombre}». "
            f"Stock actual: {producto.stock_actual}.",
        )
    else:
        messages.error(request, "Cantidad inválida.")
    return redirect(request.POST.get("volver_a") or "inventario:lista_productos")


@login_required
def escaneo(request):
    return render(request, "inventario/escaneo.html")


@login_required
def buscar_por_codigo(request):
    codigo = request.GET.get("codigo", "").strip()
    if not codigo:
        return JsonResponse({"existe": False})

    try:
        producto = Producto.objects.select_related("id_categoria").get(codigo_barras=codigo)
    except Producto.DoesNotExist:
        return JsonResponse({"existe": False, "codigo": codigo})

    return JsonResponse(
        {
            "existe": True,
            "producto": {
                "id_producto": producto.id_producto,
                "nombre": producto.nombre,
                "categoria": producto.id_categoria.nombre,
                "precio": str(producto.precio),
                "stock_actual": producto.stock_actual,
                "stock_minimo": producto.stock_minimo,
                "stock_bajo": producto.stock_bajo,
            },
        }
    )


@login_required
def lista_categorias(request):
    categorias = Categoria.objects.all()
    if request.method == "POST":
        form = CategoriaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Categoría creada.")
            return redirect("inventario:lista_categorias")
    else:
        form = CategoriaForm()

    return render(
        request,
        "inventario/lista_categorias.html",
        {"categorias": categorias, "form": form},
    )


@require_POST
@login_required
def eliminar_categoria(request, id_categoria):
    categoria = get_object_or_404(Categoria, pk=id_categoria)
    nombre = categoria.nombre
    try:
        categoria.delete()
        messages.success(request, f"Categoría «{nombre}» eliminada.")
    except ProtectedError:
        messages.error(request, f"No se puede eliminar «{nombre}»: tiene productos asociados.")
    return redirect("inventario:lista_categorias")
