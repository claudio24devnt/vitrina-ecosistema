"""Integración y sistema: API de ventas, caja, comprobante, anulación y ajuste."""

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.inventario.models import MotivoAjuste, MovimientoStock, Producto, TipoMovimiento
from apps.ventas.models import EstadoVenta, MedioPago, Venta

URL_VENTA = "/api/ventas/"
URL_ALTA = "/api/productos/alta-rapida/"


def _post(client, url, datos):
    return client.post(url, datos, content_type="application/json")


def _cuerpo(producto, cantidad=1, **cambios):
    datos = {
        "lineas": [{"id_producto": producto.pk, "cantidad": cantidad}],
        "medio_pago": MedioPago.DEBITO,
        "hora_inicio": (timezone.now() - timedelta(seconds=30)).isoformat(),
    }
    datos.update(cambios)
    return datos


@pytest.mark.django_db
class TestAPIRegistrarVenta:
    @pytest.mark.parametrize("rol", ["admin", "vendedor"])
    def test_ambos_roles_registran_ventas(self, client, datos_a, rol):
        client.force_login(getattr(datos_a, rol))
        respuesta = _post(client, URL_VENTA, _cuerpo(datos_a.producto, 2))
        assert respuesta.status_code == 201
        venta = Venta.objects.del_almacen(datos_a.almacen).get(pk=respuesta.json()["id_venta"])
        assert venta.total == 2000
        assert venta.hora_inicio is not None
        assert respuesta.json()["url_comprobante"] == reverse(
            "ventas:comprobante", args=[venta.pk]
        )

    def test_falta_stock_pide_confirmacion_y_luego_registra(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = _post(client, URL_VENTA, _cuerpo(datos_a.producto, 13))
        assert respuesta.status_code == 409
        (diferencia,) = respuesta.json()["diferencias"]
        assert diferencia["unidades"] == 3
        assert (
            "se registra una diferencia de inventario de 3 unidades" in diferencia["mensaje"]
        )
        assert Venta.objects.del_almacen(datos_a.almacen).count() == 1

        confirmada = _post(
            client, URL_VENTA, _cuerpo(datos_a.producto, 13, confirmar_diferencias=True)
        )
        assert confirmada.status_code == 201
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 0

    @pytest.mark.parametrize(
        "cambios,mensaje",
        [
            ({"medio_pago": "trueque"}, "medio de pago"),
            ({"lineas": []}, "datos inválidos"),
            ({"lineas": [{"id_producto": 1, "cantidad": 0}]}, "datos inválidos"),
            ({"lineas": [{"id_producto": "x", "cantidad": 1}]}, "datos inválidos"),
        ],
    )
    def test_datos_invalidos(self, client, datos_a, cambios, mensaje):
        client.force_login(datos_a.vendedor)
        respuesta = _post(client, URL_VENTA, _cuerpo(datos_a.producto, **cambios))
        assert respuesta.status_code == 400
        assert mensaje in respuesta.json()["detalle"]

    def test_no_vende_productos_de_otro_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.vendedor)
        respuesta = _post(client, URL_VENTA, _cuerpo(datos_b.producto))
        assert respuesta.status_code == 400
        datos_b.producto.refresh_from_db()
        assert datos_b.producto.stock_actual == 10

    def test_precio_enviado_por_el_cliente_se_ignora(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        cuerpo = _cuerpo(datos_a.producto)
        cuerpo["lineas"][0]["precio"] = 1
        cuerpo["total"] = 1
        respuesta = _post(client, URL_VENTA, cuerpo)
        assert respuesta.json()["total"] == 1000

    def test_sin_sesion_y_sin_csrf(self, client, datos_a):
        assert _post(client, URL_VENTA, _cuerpo(datos_a.producto)).status_code == 403
        estricto = Client(enforce_csrf_checks=True)
        estricto.force_login(datos_a.vendedor)
        assert _post(estricto, URL_VENTA, _cuerpo(datos_a.producto)).status_code == 403


@pytest.mark.django_db
class TestAPIAltaRapida:
    def test_vendedor_registra_y_vende_sin_abandonar_la_venta(self, client, datos_a):
        """Prueba de sistema de CU-02 2a de punta a punta por la API de la caja."""
        client.force_login(datos_a.vendedor)
        assert client.get("/api/productos/codigo/7809990000028/").status_code == 404

        alta = _post(
            client,
            URL_ALTA,
            {
                "codigo_barras": "7809990000028",
                "nombre": "Pan Amasado Ficticio",
                "precio": 250,
            },
        )
        assert alta.status_code == 201
        producto = alta.json()["producto"]
        assert (producto["stock_actual"], producto["categoria"]) == (0, None)

        venta = _post(
            client,
            URL_VENTA,
            {
                "lineas": [
                    {
                        "id_producto": producto["id_producto"],
                        "cantidad": 4,
                        "alta_rapida": True,
                    }
                ],
                "medio_pago": MedioPago.EFECTIVO,
            },
        )
        assert venta.status_code == 201  # sin pasar por el aviso 6a
        guardado = Producto.objects.del_almacen(datos_a.almacen).get(
            pk=producto["id_producto"]
        )
        assert guardado.stock_actual == 0
        assert guardado.id_usuario_creacion == datos_a.vendedor
        ajuste = MovimientoStock.objects.del_almacen(datos_a.almacen).get(
            id_producto=guardado, tipo=TipoMovimiento.AJUSTE
        )
        assert (ajuste.cantidad, ajuste.motivo) == (4, MotivoAjuste.ALTA_RAPIDA)

    def test_codigo_existente_devuelve_el_producto(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = _post(
            client,
            URL_ALTA,
            {"codigo_barras": datos_a.producto.codigo_barras, "nombre": "Otro", "precio": 1},
        )
        assert respuesta.status_code == 409
        assert respuesta.json()["producto"]["id_producto"] == datos_a.producto.pk

    @pytest.mark.parametrize(
        "datos",
        [
            {"codigo_barras": "1", "nombre": "", "precio": 100},
            {"codigo_barras": "1", "nombre": "X", "precio": -1},
            {"codigo_barras": "", "nombre": "X", "precio": 100},
        ],
    )
    def test_datos_invalidos(self, client, datos_a, datos):
        client.force_login(datos_a.vendedor)
        assert _post(client, URL_ALTA, datos).status_code == 400

    def test_el_producto_queda_en_el_almacen_del_usuario(self, client, datos_a, datos_b):
        client.force_login(datos_b.vendedor)
        _post(client, URL_ALTA, {"codigo_barras": "SOLO-B", "nombre": "De B", "precio": 10})
        assert (
            not Producto.objects.del_almacen(datos_a.almacen)
            .filter(codigo_barras="SOLO-B")
            .exists()
        )


@pytest.mark.django_db
class TestPantallasDeVentas:
    def test_caja_para_ambos_roles(self, client, datos_a):
        for usuario in (datos_a.vendedor, datos_a.admin):
            client.force_login(usuario)
            contenido = client.get(reverse("ventas:caja")).content.decode()
            assert 'id="campo-codigo"' in contenido
            assert "Débito" in contenido

    def test_comprobante_declara_que_no_es_boleta(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        contenido = client.get(
            reverse("ventas:comprobante", args=[datos_a.venta.pk])
        ).content.decode()
        assert "Comprobante interno de venta — no es boleta electrónica" in contenido
        assert "$2.000" in contenido
        assert datos_a.almacen.rut in contenido

    def test_comprobante_de_otro_almacen_no_se_ve(self, client, datos_a, datos_b):
        client.force_login(datos_a.vendedor)
        respuesta = client.get(reverse("ventas:comprobante", args=[datos_b.venta.pk]))
        assert respuesta.status_code == 404

    def test_ventas_del_dia_solo_del_almacen_y_sin_anuladas_en_el_total(
        self, client, datos_a, datos_b
    ):
        client.force_login(datos_a.vendedor)
        _post(client, URL_VENTA, _cuerpo(datos_a.producto, 1))
        venta = Venta.objects.del_almacen(datos_a.almacen).latest("pk")
        client.post(reverse("ventas:anular", args=[venta.pk]), {"motivo": "Prueba anulada"})

        respuesta = client.get(reverse("ventas:ventas_del_dia"))
        ids = [v.pk for v in respuesta.context["ventas"]]
        assert datos_b.venta.pk not in ids
        assert respuesta.context["resumen"]["anuladas"] == 1
        assert respuesta.context["resumen"]["total"] == 2000  # sólo la vigente de conftest

    def test_fecha_invalida_muestra_hoy(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.get(reverse("ventas:ventas_del_dia"), {"fecha": "ayer"})
        assert respuesta.context["es_hoy"] is True


@pytest.mark.django_db
class TestPantallaAnular:
    def test_vendedor_anula_con_motivo(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.post(
            reverse("ventas:anular", args=[datos_a.venta.pk]),
            {"motivo": "Cobré dos veces"},
            follow=True,
        )
        contenido = respuesta.content.decode()
        assert "anulada" in contenido
        assert "VENTA ANULADA" in contenido
        datos_a.venta.refresh_from_db()
        assert datos_a.venta.estado == EstadoVenta.ANULADA

    def test_motivo_corto_no_anula(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.post(
            reverse("ventas:anular", args=[datos_a.venta.pk]), {"motivo": "x"}, follow=True
        )
        assert "al menos 5 letras" in respuesta.content.decode()
        datos_a.venta.refresh_from_db()
        assert datos_a.venta.estado == EstadoVenta.VIGENTE

    def test_fuera_de_plazo_informa_el_motivo(self, client, datos_a):
        Venta.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.venta.pk).update(
            fecha_hora=timezone.now() - timedelta(days=2)
        )
        client.force_login(datos_a.vendedor)
        url = reverse("ventas:comprobante", args=[datos_a.venta.pk])
        assert "El plazo para anular esta venta ya terminó" in client.get(url).content.decode()
        respuesta = client.post(
            reverse("ventas:anular", args=[datos_a.venta.pk]),
            {"motivo": "Demasiado tarde"},
            follow=True,
        )
        assert "Ya no se puede anular" in respuesta.content.decode()

    def test_anular_requiere_post(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        assert client.get(reverse("ventas:anular", args=[datos_a.venta.pk])).status_code == 405

    def test_no_anula_ventas_de_otro_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("ventas:anular", args=[datos_b.venta.pk]), {"motivo": "Intento ajeno"}
        )
        assert respuesta.status_code == 404


@pytest.mark.django_db
class TestPantallaAjuste:
    def test_admin_ajusta_hacia_abajo(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            reverse("inventario:ajustar", args=[datos_a.producto.pk]),
            {"cantidad_contada": 7, "motivo": MotivoAjuste.PRODUCTO_VENCIDO},
        )
        assert respuesta.status_code == 302
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 7

    def test_vendedor_no_ajusta(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        url = reverse("inventario:ajustar", args=[datos_a.producto.pk])
        assert client.get(url).status_code == 403

    def test_el_formulario_solo_ofrece_los_cuatro_motivos_manuales(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = client.get(reverse("inventario:ajustar", args=[datos_a.producto.pk]))
        opciones = [valor for valor, _ in respuesta.context["form"].fields["motivo"].choices]
        assert MotivoAjuste.ALTA_RAPIDA not in opciones
        assert MotivoAjuste.VENTA_SIN_STOCK not in opciones
        assert len([o for o in opciones if o]) == 4

    def test_motivo_de_la_caja_enviado_a_mano_es_rechazado(self, client, datos_a):
        client.force_login(datos_a.admin)
        client.post(
            reverse("inventario:ajustar", args=[datos_a.producto.pk]),
            {"cantidad_contada": 7, "motivo": MotivoAjuste.VENTA_SIN_STOCK},
        )
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 10
