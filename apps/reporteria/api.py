"""
API REST de reportería (JSON), para integraciones externas (§5).

GET /api/reportes/mensual/?mes=AAAA-MM   reporte mensual (CU-04); registra el acceso
"""

from dataclasses import asdict

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.permisos import EsAdministrador

from .servicios import consultar_reporte_mensual, leer_mes


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
        datos = asdict(reporte)
        datos["mes_parcial"] = reporte.mes_parcial
        return Response(datos)
