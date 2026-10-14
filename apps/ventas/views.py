from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario

from .models import EstadoVenta, MedioPago, Venta
from .services import VentaError, anular_venta, plazo_anulacion_vencido, registrar_venta


@login_required
def punto_venta(request):
    """
    Caja: el carrito se arma en el navegador escaneando productos
    (static/js/venta.js) y se envía como un POST normal con listas
    paralelas id_producto[] / cantidad[]. Precios y stock se validan acá.
    """
    if request.method == "POST":
        ids = request.POST.getlist("id_producto")
        cantidades = request.POST.getlist("cantidad")
        medio_pago = request.POST.get("medio_pago", "")

        if medio_pago not in MedioPago.values:
            messages.error(request, "Seleccioná un medio de pago válido.")
        elif len(ids) != len(cantidades):
            messages.error(request, "El carrito llegó incompleto. Volvé a intentarlo.")
        else:
            try:
                venta = registrar_venta(
                    usuario=request.user,
                    items=list(zip(ids, cantidades)),
                    medio_pago=medio_pago,
                )
            except (VentaError, ValueError) as error:
                mensaje = str(error) if isinstance(error, VentaError) else "Cantidad inválida."
                messages.error(request, mensaje)
            else:
                messages.success(
                    request, f"Venta #{venta.id_venta} registrada. Total: ${venta.total:.0f}."
                )
                return redirect("ventas:punto_venta")

    return render(request, "ventas/punto_venta.html", {"medios_pago": MedioPago.choices})


def _fecha_desde_query(valor):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return timezone.localdate()


@login_required
def lista_ventas(request):
    fecha = _fecha_desde_query(request.GET.get("fecha"))
    ventas = (
        Venta.objects.select_related("id_usuario")
        .filter(fecha_hora__date=fecha)
        .annotate(total_items=Sum("detalles__cantidad"))
    )

    resumen = Venta.objects.filter(
        fecha_hora__date=fecha, estado=EstadoVenta.VIGENTE
    ).aggregate(cantidad=Count("id_venta"), monto=Sum("total"))
    resumen["anuladas"] = Venta.objects.filter(
        fecha_hora__date=fecha, estado=EstadoVenta.ANULADA
    ).count()

    return render(
        request,
        "ventas/lista_ventas.html",
        {"ventas": ventas, "fecha": fecha, "resumen": resumen},
    )


@login_required
def detalle_venta(request, id_venta):
    venta = get_object_or_404(Venta.objects.select_related("id_usuario"), pk=id_venta)
    detalles = venta.detalles.select_related("id_producto")
    anulable = venta.estado == EstadoVenta.VIGENTE and not plazo_anulacion_vencido(venta)
    return render(
        request,
        "ventas/detalle_venta.html",
        {"venta": venta, "detalles": detalles, "anulable": anulable},
    )


@require_POST
@rol_requerido(RolUsuario.ADMIN)
def anular(request, id_venta):
    venta = get_object_or_404(Venta, pk=id_venta)
    try:
        anular_venta(venta=venta, usuario=request.user)
    except VentaError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Venta #{venta.id_venta} anulada. Se repuso el stock.")
    return redirect("ventas:detalle_venta", id_venta=venta.id_venta)
