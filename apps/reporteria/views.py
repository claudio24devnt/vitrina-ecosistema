from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario

from .models import Alerta
from .servicios import (
    consultar_reporte_mensual,
    hoy_local,
    leer_mes,
    marcar_alerta_vista,
    mes_anterior,
    meses_disponibles,
    nombre_mes,
    primer_dia,
)

solo_admin = rol_requerido(RolUsuario.ADMIN)


@solo_admin
def reporte_mensual(request):
    """CU-04. Sólo el administrador (el vendedor no ve reportes, CU-06)."""
    hoy = hoy_local()
    meses = meses_disponibles(request.almacen, hoy)
    # Por omisión, el último mes cerrado: es el que avisa el cierre de mes.
    mes = leer_mes(request.GET.get("mes")) or mes_anterior(primer_dia(hoy))
    try:
        reporte = consultar_reporte_mensual(
            almacen=request.almacen, usuario=request.user, mes=mes, hoy=hoy
        )
    except ReglaDeNegocioError as error:
        messages.error(request, str(error))
        return redirect("reporteria:reporte_mensual")
    return render(
        request,
        "reporteria/reporte_mensual.html",
        {
            "reporte": reporte,
            "meses": [(m, nombre_mes(m).capitalize()) for m in meses],
        },
    )


@require_POST
@solo_admin
def marcar_vista(request, id_alerta):
    alerta = get_object_or_404(Alerta.objects.del_almacen(request.almacen), pk=id_alerta)
    marcar_alerta_vista(almacen=request.almacen, alerta=alerta, usuario=request.user)
    return redirect("inicio")
