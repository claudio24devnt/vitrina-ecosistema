from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.inventario.models import Producto
from apps.inventario.servicios import productos_con_stock_bajo
from apps.reporteria.servicios import alertas_del_panel


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
