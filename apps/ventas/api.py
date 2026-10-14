"""
API REST de ventas (JSON). La usa la caja (static/js/caja.js).

POST /api/ventas/            registra la venta en una transacción (CU-02)
POST /api/productos/alta-rapida/  alta rápida desde la caja (CU-02 2a)
"""

from django.urls import reverse
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.almacenes.errores import ReglaDeNegocioError
from apps.inventario.api import ProductoSerializer
from apps.inventario.servicios import CodigoDuplicadoError, registrar_producto

from .models import MedioPago
from .servicios import LineaVenta, StockInsuficienteError, registrar_venta


class LineaSerializer(serializers.Serializer):
    id_producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1, max_value=9999)
    alta_rapida = serializers.BooleanField(default=False)


class VentaSerializer(serializers.Serializer):
    lineas = LineaSerializer(many=True, allow_empty=False)
    medio_pago = serializers.ChoiceField(choices=MedioPago.choices)
    hora_inicio = serializers.DateTimeField(required=False, allow_null=True)
    confirmar_diferencias = serializers.BooleanField(default=False)


class AltaRapidaSerializer(serializers.Serializer):
    codigo_barras = serializers.CharField(max_length=20)
    nombre = serializers.CharField(max_length=150)
    precio = serializers.IntegerField(min_value=0, max_value=9_999_999_999)


def _error(mensaje, codigo=status.HTTP_400_BAD_REQUEST):
    return Response({"detalle": mensaje}, status=codigo)


class RegistrarVentaAPI(APIView):
    """Ambos roles. 201 venta registrada · 409 falta confirmar diferencias · 400 error."""

    def post(self, request):
        datos = VentaSerializer(data=request.data)
        if not datos.is_valid():
            if "medio_pago" in datos.errors:
                return _error("Elige un medio de pago.")
            return _error("La venta tiene datos inválidos. Revisa los productos y cantidades.")
        valores = datos.validated_data
        try:
            venta = registrar_venta(
                almacen=request.almacen,
                usuario=request.user,
                lineas=[LineaVenta(**linea) for linea in valores["lineas"]],
                medio_pago=valores["medio_pago"],
                hora_inicio=valores.get("hora_inicio"),
                confirmar_diferencias=valores["confirmar_diferencias"],
            )
        except StockInsuficienteError as error:
            return Response(
                {
                    "requiere_confirmacion": True,
                    "diferencias": [
                        {
                            "id_producto": d.id_producto,
                            "nombre": d.nombre,
                            "stock": d.stock,
                            "cantidad": d.cantidad,
                            "unidades": d.unidades,
                            "mensaje": d.mensaje,
                        }
                        for d in error.diferencias
                    ],
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ReglaDeNegocioError as error:
            return _error(str(error))
        return Response(
            {
                "id_venta": venta.id_venta,
                "total": int(venta.total),
                "url_comprobante": reverse("ventas:comprobante", args=[venta.id_venta]),
            },
            status=status.HTTP_201_CREATED,
        )


class AltaRapidaAPI(APIView):
    """
    Ambos roles (decidido 2026-10-14). Sólo código, nombre y precio; sin categoría ni
    stock. 201 creado · 409 el código ya existía (devuelve ese producto) · 400 error.
    """

    def post(self, request):
        datos = AltaRapidaSerializer(data=request.data)
        if not datos.is_valid():
            return _error("Escribe el nombre y un precio válido.")
        valores = datos.validated_data
        try:
            producto = registrar_producto(
                almacen=request.almacen,
                usuario=request.user,
                codigo_barras=valores["codigo_barras"],
                nombre=valores["nombre"],
                precio=valores["precio"],
            )
        except CodigoDuplicadoError as error:
            return Response(
                {"producto": ProductoSerializer(error.producto).data},
                status=status.HTTP_409_CONFLICT,
            )
        except ReglaDeNegocioError as error:
            return _error(str(error))
        return Response(
            {"producto": ProductoSerializer(producto).data}, status=status.HTTP_201_CREATED
        )
