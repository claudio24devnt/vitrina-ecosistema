"""
Pruebas de sistema (1.4.5): los seis casos de uso recorridos como los usaría el
almacén, de punta a punta y cruzando módulos. A diferencia de las de integración,
inician sesión con el formulario real y el CSRF está activo, como en el navegador.
Todos los datos son FICTICIOS.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.inventario.models import MotivoAjuste, MovimientoStock, Producto, TipoMovimiento
from apps.reporteria.models import AccesoReporte, Alerta, TipoAlerta
from apps.reporteria.servicios import hoy_local
from apps.usuarios.models import RolUsuario, Usuario
from apps.ventas.models import EstadoVenta, MedioPago, Venta

CLAVE_VENDEDORA = "Ficticia-2026-segura"


class Navegador:
    """Cliente con CSRF obligatorio que manda el token como lo hacen las pantallas."""

    def __init__(self):
        self.cliente = Client(enforce_csrf_checks=True)

    def _token(self):
        if "csrftoken" not in self.cliente.cookies:
            self.cliente.get(reverse("usuarios:login"))
        return self.cliente.cookies["csrftoken"].value

    def get(self, url, datos=None, **extra):
        return self.cliente.get(url, datos, **extra)

    def enviar(self, url, datos, **extra):
        """POST de formulario."""
        return self.cliente.post(url, {**datos, "csrfmiddlewaretoken": self._token()}, **extra)

    def api(self, url, datos):
        """POST JSON con X-CSRFToken, como caja.js y escanear.js."""
        return self.cliente.post(
            url, datos, content_type="application/json", HTTP_X_CSRFTOKEN=self._token()
        )

    def iniciar_sesion(self, email, clave):
        respuesta = self.enviar(
            reverse("usuarios:login"), {"username": email, "password": clave}
        )
        assert respuesta.status_code == 302, "no pudo iniciar sesión"
        return self

    def cerrar_sesion(self):
        self.enviar(reverse("usuarios:logout"), {})


def _venta(navegador, lineas, **extra):
    cuerpo = {
        "lineas": lineas,
        "medio_pago": MedioPago.EFECTIVO,
        "hora_inicio": (timezone.now() - timedelta(seconds=40)).isoformat(),
        **extra,
    }
    return navegador.api("/api/ventas/", cuerpo)


@pytest.fixture
def admin(datos_a):
    return Navegador().iniciar_sesion(datos_a.admin.email, "clave-de-prueba")


@pytest.mark.django_db
class TestJornadaCompleta:
    """CU-06 → CU-01 → CU-02 (con 2a y 6a) → CU-03 → CU-05 → CU-04, en ese orden."""

    def test_un_dia_en_el_almacen(self, datos_a, admin):
        almacen = datos_a.almacen

        # CU-06: el administrador crea a la vendedora.
        respuesta = admin.enviar(
            reverse("usuarios:vendedores"),
            {
                "nombre": "Vendedora Ficticia Nueva",
                "email": "nueva@ficticio.test",
                "password": CLAVE_VENDEDORA,
                "password_repetida": CLAVE_VENDEDORA,
            },
        )
        assert respuesta.status_code == 302
        vendedora_db = Usuario.objects.del_almacen(almacen).get(email="nueva@ficticio.test")
        assert vendedora_db.rol == RolUsuario.VENDEDOR
        assert vendedora_db.password != CLAVE_VENDEDORA  # guardada con hash

        # CU-01: escanea un código que no existe y lo registra con stock inicial.
        assert admin.get("/api/productos/codigo/7801234500017/").status_code == 404
        formulario = admin.get(
            reverse("inventario:nuevo_producto"), {"codigo": "7801234500017"}
        )
        assert 'value="7801234500017"' in formulario.content.decode()
        respuesta = admin.enviar(
            reverse("inventario:nuevo_producto"),
            {
                "codigo_barras": "7801234500017",
                "nombre": "Galletas Ficticias de Avena",
                "categoria": datos_a.categoria.pk,
                "precio": "890",
                "stock_minimo": "2",
                "stock_inicial": "3",
            },
        )
        assert respuesta.status_code == 302
        galletas = Producto.objects.del_almacen(almacen).get(codigo_barras="7801234500017")
        assert galletas.stock_actual == 3

        # CU-02: la vendedora inicia sesión y vende.
        vendedora = Navegador().iniciar_sesion("nueva@ficticio.test", CLAVE_VENDEDORA)
        assert vendedora.get(reverse("ventas:caja")).status_code == 200
        encontrado = vendedora.get("/api/productos/codigo/7801234500017/").json()
        assert encontrado["producto"]["id_producto"] == galletas.pk

        # 6a: vende 5 y el sistema tiene 3: primero avisa sin registrar nada.
        aviso = _venta(vendedora, [{"id_producto": galletas.pk, "cantidad": 5}])
        assert aviso.status_code == 409
        assert aviso.json()["diferencias"][0]["mensaje"] == (
            "El sistema tiene 3 unidades de «Galletas Ficticias de Avena» y estás vendiendo "
            "5. Si continúas, se registra una diferencia de inventario de 2 unidades."
        )
        assert Venta.objects.del_almacen(almacen).count() == 1  # sólo la de la fixture

        # 2a: en la misma venta escanea un producto que no existe y lo da de alta.
        assert vendedora.get("/api/productos/codigo/7809999000013/").status_code == 404
        alta = vendedora.api(
            "/api/productos/alta-rapida/",
            {
                "codigo_barras": "7809999000013",
                "nombre": "Jugo Ficticio en Caja",
                "precio": 600,
            },
        )
        assert alta.status_code == 201
        jugo = alta.json()["producto"]

        confirmada = _venta(
            vendedora,
            [
                {"id_producto": galletas.pk, "cantidad": 5},
                {"id_producto": jugo["id_producto"], "cantidad": 1, "alta_rapida": True},
            ],
            confirmar_diferencias=True,
        )
        assert confirmada.status_code == 201
        venta = Venta.objects.del_almacen(almacen).get(pk=confirmada.json()["id_venta"])
        assert venta.total == 5 * 890 + 600
        assert venta.hora_inicio < venta.fecha_hora
        galletas.refresh_from_db()
        assert galletas.stock_actual == 0  # nunca negativo

        ajustes = MovimientoStock.objects.del_almacen(almacen).filter(
            id_venta=venta, tipo=TipoMovimiento.AJUSTE
        )
        assert sorted(ajustes.values_list("motivo", "cantidad")) == [
            (MotivoAjuste.ALTA_RAPIDA, 1),
            (MotivoAjuste.VENTA_SIN_STOCK, 2),
        ]

        comprobante = vendedora.get(confirmada.json()["url_comprobante"]).content.decode()
        assert "Comprobante interno de venta — no es boleta electrónica" in comprobante

        # CU-03: la vendedora anula la venta el mismo día, con motivo.
        respuesta = vendedora.enviar(
            reverse("ventas:anular", args=[venta.pk]), {"motivo": "Cliente se arrepintió"}
        )
        assert respuesta.status_code == 302
        venta.refresh_from_db()
        assert venta.estado == EstadoVenta.ANULADA
        assert venta.id_usuario_anulacion == vendedora_db
        galletas.refresh_from_db()
        assert galletas.stock_actual == 5  # vuelven las 5 vendidas

        # El vendedor no ve reportes (CU-06).
        assert vendedora.get(reverse("reporteria:reporte_mensual")).status_code == 403

        # CU-05: la revisión diaria deja la alerta y el administrador la ve en el panel.
        # La bebida de la fixture tiene 10 con mínimo 2: no entra en la alerta.
        Producto.objects.del_almacen(almacen).filter(pk=galletas.pk).update(stock_minimo=5)
        call_command("alertar_stock_bajo", stdout=StringIO())
        alerta = Alerta.objects.del_almacen(almacen).get(
            tipo=TipoAlerta.STOCK_BAJO, fecha_referencia=hoy_local()
        )
        # Sólo las galletas (5 de mínimo 5): el jugo volvió a 1 al anular y su mínimo es 0.
        assert alerta.mensaje.startswith("Hay 1 producto con stock bajo el mínimo")
        panel = admin.get(reverse("inicio")).content.decode()
        assert alerta.mensaje in panel
        admin.enviar(reverse("reporteria:marcar_vista", args=[alerta.pk]), {})
        assert alerta.mensaje not in admin.get(reverse("inicio")).content.decode()

        # CU-04: el reporte del mes cuenta la venta vigente de la fixture, no la anulada.
        mes = hoy_local().strftime("%Y-%m")
        reporte = admin.get(reverse("reporteria:reporte_mensual"), {"mes": mes})
        assert reporte.status_code == 200
        assert reporte.context["reporte"].cantidad_ventas == 1
        assert (
            AccesoReporte.objects.del_almacen(almacen).filter(id_usuario=datos_a.admin).count()
            == 2
        )


@pytest.mark.django_db
class TestAlternativos:
    def test_cu01_1a_codigo_ilegible_se_digita_a_mano(self, admin):
        # El campo de escaneo es texto: digitar el código y Enter es lo mismo que escanear.
        pagina = admin.get(reverse("inventario:escanear")).content.decode()
        assert "autofocus" in pagina
        assert admin.get("/api/productos/codigo/%207800000000017%20/").json()["existe"]

    def test_cu01_2a_codigo_existente_ofrece_sumar_stock(self, datos_a, admin):
        respuesta = admin.enviar(
            reverse("inventario:nuevo_producto"),
            {
                "codigo_barras": datos_a.producto.codigo_barras,
                "nombre": "Duplicado",
                "precio": "100",
                "stock_minimo": "0",
                "stock_inicial": "1",
            },
            follow=True,
        )
        assert (
            "Ese código de barras ya está registrado en Bebidas" in respuesta.content.decode()
        )
        sumar = admin.api(f"/api/productos/{datos_a.producto.pk}/entradas/", {"cantidad": 4})
        assert sumar.status_code == 200
        datos_a.producto.refresh_from_db()
        assert datos_a.producto.stock_actual == 14

    def test_cu03_2a_fuera_de_plazo_se_rechaza_con_el_motivo(self, datos_a, admin):
        ayer = timezone.now() - timedelta(days=1)
        Venta.objects.del_almacen(datos_a.almacen).filter(pk=datos_a.venta.pk).update(
            fecha_hora=ayer
        )
        respuesta = admin.enviar(
            reverse("ventas:anular", args=[datos_a.venta.pk]),
            {"motivo": "Motivo ficticio"},
            follow=True,
        )
        assert "Ya no se puede anular" in respuesta.content.decode()
        datos_a.venta.refresh_from_db()
        assert datos_a.venta.estado == EstadoVenta.VIGENTE

    def test_cu04_2a_mes_sin_ventas_lo_informa(self, admin):
        respuesta = admin.get(reverse("reporteria:reporte_mensual"), {"mes": "2026-01"})
        assert "No hay ventas registradas en enero 2026." in respuesta.content.decode()

    def test_cu05_3a_sin_productos_bajo_el_minimo_no_hay_alerta(self, datos_a):
        call_command("alertar_stock_bajo", stdout=StringIO())
        tipo = TipoAlerta.STOCK_BAJO
        # La fixture trae una alerta antigua; hoy no se agrega ninguna.
        alertas = Alerta.objects.del_almacen(datos_a.almacen).filter(tipo=tipo)
        assert not alertas.filter(fecha_referencia=hoy_local()).exists()

    def test_cu06_2a_correo_ya_registrado_se_informa(self, datos_a, admin):
        respuesta = admin.enviar(
            reverse("usuarios:vendedores"),
            {
                "nombre": "Repetido",
                "email": datos_a.vendedor.email,
                "password": CLAVE_VENDEDORA,
                "password_repetida": CLAVE_VENDEDORA,
            },
        )
        assert "Ese correo ya está registrado" in respuesta.content.decode()


@pytest.mark.django_db
class TestSeguridadDeExtremoAExtremo:
    def test_sin_token_csrf_no_se_registra_la_venta(self, datos_a, admin):
        respuesta = admin.cliente.post(
            "/api/ventas/",
            {
                "lineas": [{"id_producto": datos_a.producto.pk, "cantidad": 1}],
                "medio_pago": "efectivo",
            },
            content_type="application/json",
        )
        assert respuesta.status_code == 403
        assert Venta.objects.del_almacen(datos_a.almacen).count() == 1

    def test_tras_cerrar_sesion_no_hay_acceso(self, admin):
        admin.cerrar_sesion()
        assert admin.get(reverse("inicio")).status_code == 302
        assert admin.get("/api/productos/codigo/7800000000017/").status_code == 403

    def test_un_almacen_no_llega_a_datos_del_otro_por_ninguna_pantalla(self, datos_a, datos_b):
        intruso = Navegador().iniciar_sesion(datos_b.admin.email, "clave-de-prueba")
        ajenos = [
            reverse("ventas:comprobante", args=[datos_a.venta.pk]),
            reverse("inventario:editar_producto", args=[datos_a.producto.pk]),
            reverse("inventario:ajustar", args=[datos_a.producto.pk]),
        ]
        for url in ajenos:
            assert intruso.get(url).status_code == 404, url
        assert (
            intruso.enviar(
                reverse("reporteria:marcar_vista", args=[datos_a.alerta.pk]), {}
            ).status_code
            == 404
        )
        venta_ajena = _venta(intruso, [{"id_producto": datos_a.producto.pk, "cantidad": 1}])
        assert venta_ajena.status_code == 400
        assert Venta.objects.del_almacen(datos_a.almacen).count() == 1
