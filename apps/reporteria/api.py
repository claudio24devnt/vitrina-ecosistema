"""
API REST de reportería (JSON), para integraciones externas (§5).

GET /api/reportes/mensual/?mes=AAAA-MM   reporte mensual (CU-04); registra el acceso
GET /api/reportes/?periodo=semana&semana=AAAA-MM-DD | periodo=mes&mes=AAAA-MM |
    periodo=anio&anio=AAAA                reporte del período; registra el acceso
"""

from dataclasses import asdict

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.permisos import EsAdministrador

from .models import TipoPeriodo
from .periodos import leer_periodo
from .servicios import consultar_reporte, consultar_reporte_mensual, leer_mes


def _json(reporte):
    datos = asdict(reporte)
    datos["periodo"] = {
        "tipo": reporte.periodo.tipo,
        "inicio": reporte.periodo.inicio,
        "fin": reporte.periodo.fin,
        "nombre": reporte.periodo.nombre,
    }
    datos["mes"] = reporte.mes
    datos["mes_parcial"] = reporte.mes_parcial
    datos["ticket_promedio"] = reporte.ticket_promedio
    return datos


class ReporteMensualAPI(APIView):
    """Sólo el administrador. 200 reporte (con `hay_ventas` falso si no hay datos) · 400."""

    permission_classes = [EsAdministrador]

    def get(self, request):
        mes = leer_mes(request.query_params.get("mes"))
        if mes is None:
            return Response(
                {"detalle": "Indica el mes con el formato AAAA-MM, por ejemplo 2026-09."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            reporte = consultar_reporte_mensual(
                almacen=request.almacen, usuario=request.user, mes=mes
            )
        except ReglaDeNegocioError as error:
            return Response({"detalle": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_json(reporte))


class ReporteAPI(APIView):
    """Sólo el administrador. Igual que el mensual, para semana, mes o año. 200 · 400."""

    permission_classes = [EsAdministrador]
    PARAMETRO = {
        TipoPeriodo.SEMANA: "semana",
        TipoPeriodo.MES: "mes",
        TipoPeriodo.ANIO: "anio",
    }

    def get(self, request):
        tipo = request.query_params.get("periodo")
        if tipo not in TipoPeriodo.values:
            return Response(
                {"detalle": "Indica el período: semana, mes o anio."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        periodo = leer_periodo(tipo, request.query_params.get(self.PARAMETRO[tipo]))
        if periodo is None:
            formato = {"semana": "AAAA-MM-DD", "mes": "AAAA-MM", "anio": "AAAA"}[tipo]
            return Response(
                {"detalle": f"Indica {self.PARAMETRO[tipo]} con el formato {formato}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            reporte = consultar_reporte(
                almacen=request.almacen, usuario=request.user, periodo=periodo
            )
        except ReglaDeNegocioError as error:
            return Response({"detalle": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_json(reporte))
