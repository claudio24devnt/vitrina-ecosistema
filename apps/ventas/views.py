from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN

from .forms import AnularVentaForm
from .models import DetalleVenta, EstadoVenta, MedioPago, Venta
from .servicios import anulacion_en_plazo, anular_venta


@login_required
def caja(request):
    """Punto de venta (CU-02). Ambos roles. La lógica de la pantalla está en caja.js."""
    return render(request, "ventas/caja.html", {"medios_pago": MedioPago.choices})


def _fecha_consultada(request):
    try:
        return date.fromisoformat(request.GET.get("fecha", ""))
    except ValueError:
        return timezone.localdate(timezone=ZONA_HORARIA_ALMACEN)


@login_required
def ventas_del_dia(request):
    fecha = _fecha_consultada(request)
    ventas = (
        Venta.objects.del_almacen(request.almacen)
        .filter(fecha_hora__date=fecha)
        .select_related("id_usuario")
        .annotate(unidades=Sum("detalles__cantidad"))
        .order_by("-fecha_hora")
    )
    resumen = (
        Venta.objects.del_almacen(request.almacen)
        .filter(fecha_hora__date=fecha)
        .aggregate(
            cantidad=Count("pk", filter=Q(estado=EstadoVenta.VIGENTE)),
            total=Sum("total", filter=Q(estado=EstadoVenta.VIGENTE)),
            anuladas=Count("pk", filter=Q(estado=EstadoVenta.ANULADA)),
        )
    )
    return render(
        request,
        "ventas/ventas_del_dia.html",
        {
            "ventas": ventas,
            "fecha": fecha,
            "es_hoy": fecha == timezone.localdate(timezone=ZONA_HORARIA_ALMACEN),
            "resumen": resumen,
        },
    )


@login_required
def comprobante(request, id_venta):
    venta = get_object_or_404(
        Venta.objects.del_almacen(request.almacen).select_related(
            "id_usuario", "id_usuario_anulacion", "id_almacen"
        ),
        pk=id_venta,
    )
    detalles = (
        DetalleVenta.objects.del_almacen(request.almacen)
        .filter(id_venta=venta)
        .select_related("id_producto")
        .order_by("pk")
    )
    anulable = venta.estado == EstadoVenta.VIGENTE and anulacion_en_plazo(venta)
    return render(
        request,
        "ventas/comprobante.html",
        {
            "venta": venta,
            "detalles": detalles,
            "anulable": anulable,
            "form_anular": AnularVentaForm(),
            "recien_registrada": request.GET.get("nueva") == "1",
        },
    )


@require_POST
@login_required
def anular(request, id_venta):
    """CU-03: ambos roles (decidido 2026-10-14); el control es el registro."""
    venta = get_object_or_404(Venta.objects.del_almacen(request.almacen), pk=id_venta)
    form = AnularVentaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Escribe el motivo de la anulación (al menos 5 letras).")
        return redirect("ventas:comprobante", id_venta=venta.id_venta)
    try:
        anular_venta(
            almacen=request.almacen,
            venta=venta,
            usuario=request.user,
            motivo=form.cleaned_data["motivo"],
        )
    except ReglaDeNegocioError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request, f"Venta N° {venta.id_venta} anulada. Los productos volvieron al stock."
        )
    return redirect("ventas:comprobante", id_venta=venta.id_venta)
