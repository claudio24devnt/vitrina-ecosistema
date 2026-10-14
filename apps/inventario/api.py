"""
API REST de inventario (JSON). La usan la pantalla de escaneo y, en 1.4.3, la caja.
Toda respuesta se limita al almacén del usuario con sesión iniciada.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.permisos import EsAdministrador

from .models import Producto
from .servicios import buscar_por_codigo, registrar_entrada_stock


class ProductoSerializer(serializers.ModelSerializer):
    categoria = serializers.CharField(source="id_categoria.nombre", default=None)
    precio = serializers.IntegerField()
    stock_bajo = serializers.BooleanField()

    class Meta:
        model = Producto
        fields = [
            "id_producto",
            "codigo_barras",
            "nombre",
            "categoria",
            "precio",
            "stock_actual",
            "stock_minimo",
            "stock_bajo",
        ]


class EntradaSerializer(serializers.Serializer):
    cantidad = serializers.IntegerField(min_value=1, max_value=100000)


class ProductoPorCodigoAPI(APIView):
    """GET: busca un producto del almacén por código de barras (ambos roles)."""

    def get(self, request, codigo):
        producto = buscar_por_codigo(request.almacen, codigo)
        if producto is None:
            return Response(
                {"existe": False, "codigo": codigo.strip()}, status=status.HTTP_404_NOT_FOUND
            )
        return Response({"existe": True, "producto": ProductoSerializer(producto).data})


class EntradaStockAPI(APIView):
    """POST {cantidad}: suma stock a un producto existente (CU-01 2a, sólo administrador)."""

    permission_classes = [EsAdministrador]

    def post(self, request, id_producto):
        producto = get_object_or_404(
            Producto.objects.del_almacen(request.almacen).select_related("id_categoria"),
            pk=id_producto,
        )
        entrada = EntradaSerializer(data=request.data)
        if not entrada.is_valid():
            return Response(
                {"detalle": "Escribe una cantidad entera mayor que cero."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            registrar_entrada_stock(
                almacen=request.almacen,
                producto=producto,
                cantidad=entrada.validated_data["cantidad"],
            )
        except ReglaDeNegocioError as error:
            return Response({"detalle": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"producto": ProductoSerializer(producto).data})
