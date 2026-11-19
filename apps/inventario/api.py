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
    # «350 ml» o null: descriptivo, para que la caja distinga variantes del mismo nombre.
    contenido = serializers.SerializerMethodField()

    def get_contenido(self, producto):
        return producto.contenido_texto or None

    class Meta:
        model = Producto
        fields = [
            "id_producto",
            "codigo_barras",
            "nombre",
            "contenido",
            "categoria",
            "precio",
            "stock_actual",
            "stock_minimo",
            "stock_bajo",
        ]


def datos_del_producto(producto, usuario):
    """
    El producto en JSON. El costo va sólo para el administrador: esta misma respuesta la
    recibe la caja del vendedor, y el vendedor no ve costos ni ganancias.
    """
    datos = ProductoSerializer(producto).data
    if usuario.es_admin:
        datos["costo"] = None if producto.costo is None else int(producto.costo)
    return datos


class EntradaSerializer(serializers.Serializer):
    cantidad = serializers.IntegerField(min_value=1, max_value=100000)
    # Costo por unidad de lo que llegó (opcional): reemplaza el costo del producto.
    costo = serializers.IntegerField(
        min_value=0, max_value=9999999999, required=False, allow_null=True
    )


class ProductoPorCodigoAPI(APIView):
    """GET: busca un producto del almacén por código de barras (ambos roles)."""

    def get(self, request, codigo):
        producto = buscar_por_codigo(request.almacen, codigo)
        if producto is None:
            return Response(
                {"existe": False, "codigo": codigo.strip()}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            {"existe": True, "producto": datos_del_producto(producto, request.user)}
        )


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
            mensaje = (
                "El costo va en pesos: un número entero, sin puntos ni signos."
                if "costo" in entrada.errors
                else "Escribe una cantidad entera mayor que cero."
            )
            return Response({"detalle": mensaje}, status=status.HTTP_400_BAD_REQUEST)
        try:
            registrar_entrada_stock(
                almacen=request.almacen,
                producto=producto,
                cantidad=entrada.validated_data["cantidad"],
                usuario=request.user,
                costo=entrada.validated_data.get("costo"),
            )
        except ReglaDeNegocioError as error:
            return Response({"detalle": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"producto": datos_del_producto(producto, request.user)})
