from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.shortcuts import render

from apps.inventario.models import Producto


@login_required
def inicio(request):
    productos = Producto.objects.del_almacen(request.almacen)
    return render(
        request,
        "inicio.html",
        {
            "total_productos": productos.count(),
            "total_stock_bajo": productos.filter(stock_actual__lte=F("stock_minimo")).count(),
        },
    )
