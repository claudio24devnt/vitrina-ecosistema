from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario

from .models import Alerta, TipoPeriodo
from .periodos import leer_periodo
from .servicios import (
    consultar_reporte,
    hoy_local,
    indicadores,
    leer_mes,
    marcar_alerta_vista,
    meses_disponibles,
    nombre_mes,
    periodo_por_omision,
    periodos_disponibles,
    primer_dia,
)

solo_admin = rol_requerido(RolUsuario.ADMIN)

# Parámetro de la URL con el valor de cada tipo: ?periodo=semana&semana=2026-11-09.
PARAMETRO = {TipoPeriodo.SEMANA: "semana", TipoPeriodo.MES: "mes", TipoPeriodo.ANIO: "anio"}


def periodo_pedido(params, almacen, hoy):
    """Tipo y período de la URL; si faltan o no se entienden, el período por omisión."""
    tipo = params.get("periodo")
    if tipo not in TipoPeriodo.values:
        tipo = TipoPeriodo.MES
    periodo = leer_periodo(tipo, params.get(PARAMETRO[tipo]))
    return periodo or periodo_por_omision(almacen, tipo, hoy)


@solo_admin
def reporte_mensual(request):
    """CU-04 por semana, mes o año. Sólo el administrador (el vendedor no ve reportes)."""
    hoy = hoy_local()
    periodo = periodo_pedido(request.GET, request.almacen, hoy)
    try:
        reporte = consultar_reporte(
            almacen=request.almacen, usuario=request.user, periodo=periodo, hoy=hoy
        )
    except ReglaDeNegocioError as error:
        messages.error(request, str(error))
        return redirect(f"{request.path}?periodo={periodo.tipo}")
    return render(
        request,
        "reporteria/reporte_mensual.html",
        {
            "reporte": reporte,
            "periodos": periodos_disponibles(request.almacen, periodo.tipo, hoy),
            "parametro": PARAMETRO[periodo.tipo],
            "tipos": TipoPeriodo.choices,
        },
    )


@solo_admin
def indicadores_del_mes(request):
    """Indicadores de §7 para el piloto. Por omisión, el mes en curso."""
    hoy = hoy_local()
    meses = meses_disponibles(request.almacen, hoy)
    mes = leer_mes(request.GET.get("mes")) or primer_dia(hoy)
    try:
        resultado = indicadores(request.almacen, mes, hoy)
    except ReglaDeNegocioError as error:
        messages.error(request, str(error))
        return redirect("reporteria:indicadores")
    return render(
        request,
        "reporteria/indicadores.html",
        {
            "ind": resultado,
            "meses": [(m, nombre_mes(m).capitalize()) for m in meses],
        },
    )


@require_POST
@solo_admin
def marcar_vista(request, id_alerta):
    alerta = get_object_or_404(Alerta.objects.del_almacen(request.almacen), pk=id_alerta)
    marcar_alerta_vista(almacen=request.almacen, alerta=alerta, usuario=request.user)
    return redirect("inicio")
