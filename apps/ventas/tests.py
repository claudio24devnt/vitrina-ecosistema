from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.inventario.models import Categoria, MovimientoStock, Producto, TipoMovimiento
from apps.usuarios.models import RolUsuario, Usuario
from apps.ventas.models import DetalleVenta, EstadoVenta, MedioPago, Venta
from apps.ventas.services import VentaError, anular_venta, registrar_venta


@pytest.fixture
def categoria(db):
    return Categoria.objects.create(nombre="Bebidas")


@pytest.fixture
def agua(categoria):
    return Producto.objects.create(
        codigo_barras="7801111111111",
        nombre="Agua Mineral 500ml",
        id_categoria=categoria,
        precio="500.00",
        stock_actual=10,
        stock_minimo=2,
    )


@pytest.fixture
def bebida(categoria):
    return Producto.objects.create(
        codigo_barras="7802222222222",
        nombre="Bebida Cola 1.5L",
        id_categoria=categoria,
        precio="1490.00",
        stock_actual=3,
        stock_minimo=1,
    )


@pytest.fixture
def vendedor(db):
    return Usuario.objects.create_user(
        email="vendedor@tivoscanea.cl", nombre="Vendedor Uno", password="clave123"
    )


@pytest.fixture
def admin(db):
    return Usuario.objects.create_user(
        email="admin@tivoscanea.cl",
        nombre="Admin Uno",
        password="clave123",
        rol=RolUsuario.ADMIN,
    )


@pytest.fixture
def venta(vendedor, agua, bebida):
    return registrar_venta(
        usuario=vendedor,
        items=[(agua.pk, 2), (bebida.pk, 1)],
        medio_pago=MedioPago.EFECTIVO,
    )


def _envejecer(venta, minutos):
    Venta.objects.filter(pk=venta.pk).update(
        fecha_hora=timezone.now() - timedelta(minutes=minutos)
    )
    venta.refresh_from_db()


@pytest.mark.django_db
class TestRegistrarVenta:
    def test_registra_detalles_total_y_descuenta_stock(self, venta, agua, bebida):
        agua.refresh_from_db()
        bebida.refresh_from_db()

        assert venta.total == Decimal("2490.00")
        assert venta.estado == EstadoVenta.VIGENTE
        assert venta.detalles.count() == 2
        detalle_agua = venta.detalles.get(id_producto=agua)
        assert detalle_agua.precio_unitario == Decimal("500.00")
        assert detalle_agua.subtotal == Decimal("1000.00")
        assert agua.stock_actual == 8
        assert bebida.stock_actual == 2

    def test_cada_descuento_genera_movimiento_salida_ligado_a_la_venta(self, venta, agua):
        movimiento = MovimientoStock.objects.get(id_producto=agua)
        assert movimiento.tipo == TipoMovimiento.SALIDA
        assert movimiento.cantidad == 2
        assert movimiento.id_venta == venta

    def test_mismo_producto_repetido_se_agrupa_en_un_detalle(self, vendedor, agua):
        venta = registrar_venta(
            usuario=vendedor, items=[(agua.pk, 1), (agua.pk, 2)], medio_pago=MedioPago.DEBITO
        )
        assert venta.detalles.count() == 1
        assert venta.detalles.first().cantidad == 3

    def test_stock_insuficiente_no_guarda_nada(self, vendedor, agua, bebida):
        with pytest.raises(VentaError, match="Stock insuficiente"):
            registrar_venta(
                usuario=vendedor,
                items=[(agua.pk, 1), (bebida.pk, 99)],
                medio_pago=MedioPago.EFECTIVO,
            )
        agua.refresh_from_db()
        assert agua.stock_actual == 10
        assert Venta.objects.count() == 0
        assert DetalleVenta.objects.count() == 0
        assert MovimientoStock.objects.count() == 0

    def test_venta_vacia_lanza_error(self, vendedor):
        with pytest.raises(VentaError):
            registrar_venta(usuario=vendedor, items=[], medio_pago=MedioPago.EFECTIVO)

    def test_cantidad_cero_lanza_error(self, vendedor, agua):
        with pytest.raises(VentaError):
            registrar_venta(
                usuario=vendedor, items=[(agua.pk, 0)], medio_pago=MedioPago.EFECTIVO
            )

    def test_producto_inexistente_lanza_error(self, vendedor):
        with pytest.raises(VentaError, match="no existen"):
            registrar_venta(usuario=vendedor, items=[(9999, 1)], medio_pago=MedioPago.EFECTIVO)


@pytest.mark.django_db
class TestAnularVenta:
    def test_admin_anula_dentro_del_plazo_y_repone_stock(self, venta, admin, agua, bebida):
        anular_venta(venta=venta, usuario=admin)
        venta.refresh_from_db()
        agua.refresh_from_db()
        bebida.refresh_from_db()

        assert venta.estado == EstadoVenta.ANULADA
        assert agua.stock_actual == 10
        assert bebida.stock_actual == 3
        reposicion = MovimientoStock.objects.get(id_producto=agua, tipo=TipoMovimiento.ENTRADA)
        assert reposicion.cantidad == 2
        assert reposicion.id_venta == venta

    def test_vendedor_no_puede_anular(self, venta, vendedor):
        with pytest.raises(VentaError, match="administrador"):
            anular_venta(venta=venta, usuario=vendedor)
        venta.refresh_from_db()
        assert venta.estado == EstadoVenta.VIGENTE

    def test_no_se_puede_anular_fuera_de_plazo(self, venta, admin, agua, settings):
        settings.PLAZO_ANULACION_VENTA_MINUTOS = 30
        _envejecer(venta, 31)
        with pytest.raises(VentaError, match="ya no se puede anular"):
            anular_venta(venta=venta, usuario=admin)
        agua.refresh_from_db()
        assert agua.stock_actual == 8

    def test_no_se_puede_anular_dos_veces(self, venta, admin, agua):
        anular_venta(venta=venta, usuario=admin)
        with pytest.raises(VentaError, match="ya está anulada"):
            anular_venta(venta=venta, usuario=admin)
        agua.refresh_from_db()
        assert agua.stock_actual == 10


@pytest.mark.django_db
class TestVistasVentas:
    def test_punto_venta_requiere_login(self, client):
        respuesta = client.get(reverse("ventas:punto_venta"))
        assert respuesta.status_code == 302

    def test_punto_venta_renderiza(self, client, vendedor):
        client.force_login(vendedor)
        respuesta = client.get(reverse("ventas:punto_venta"))
        assert respuesta.status_code == 200
        assert "Registrar venta" in respuesta.content.decode()

    def test_post_registra_venta(self, client, vendedor, agua, bebida):
        client.force_login(vendedor)
        respuesta = client.post(
            reverse("ventas:punto_venta"),
            {
                "id_producto": [agua.pk, bebida.pk],
                "cantidad": [3, 1],
                "medio_pago": MedioPago.TRANSFERENCIA,
            },
        )
        assert respuesta.status_code == 302
        venta = Venta.objects.get()
        assert venta.id_usuario == vendedor
        assert venta.total == Decimal("2990.00")
        agua.refresh_from_db()
        assert agua.stock_actual == 7

    def test_post_ignora_precio_manipulado_por_el_cliente(self, client, vendedor, agua):
        client.force_login(vendedor)
        client.post(
            reverse("ventas:punto_venta"),
            {
                "id_producto": [agua.pk],
                "cantidad": [1],
                "precio": ["1"],
                "medio_pago": MedioPago.EFECTIVO,
            },
        )
        assert Venta.objects.get().total == Decimal("500.00")

    def test_post_sin_stock_muestra_error(self, client, vendedor, bebida):
        client.force_login(vendedor)
        respuesta = client.post(
            reverse("ventas:punto_venta"),
            {"id_producto": [bebida.pk], "cantidad": [50], "medio_pago": MedioPago.EFECTIVO},
        )
        assert respuesta.status_code == 200
        assert "Stock insuficiente" in respuesta.content.decode()
        assert Venta.objects.count() == 0

    def test_post_medio_pago_invalido(self, client, vendedor, agua):
        client.force_login(vendedor)
        respuesta = client.post(
            reverse("ventas:punto_venta"),
            {"id_producto": [agua.pk], "cantidad": [1], "medio_pago": "trueque"},
        )
        assert "medio de pago" in respuesta.content.decode()
        assert Venta.objects.count() == 0

    def test_post_cantidad_no_numerica(self, client, vendedor, agua):
        client.force_login(vendedor)
        respuesta = client.post(
            reverse("ventas:punto_venta"),
            {"id_producto": [agua.pk], "cantidad": ["abc"], "medio_pago": MedioPago.EFECTIVO},
        )
        assert "Cantidad inválida" in respuesta.content.decode()
        assert Venta.objects.count() == 0

    def test_post_listas_desparejas(self, client, vendedor, agua):
        client.force_login(vendedor)
        respuesta = client.post(
            reverse("ventas:punto_venta"),
            {"id_producto": [agua.pk], "cantidad": [], "medio_pago": MedioPago.EFECTIVO},
        )
        assert "incompleto" in respuesta.content.decode()

    def test_lista_ventas_muestra_resumen_del_dia(self, client, vendedor, venta):
        client.force_login(vendedor)
        respuesta = client.get(reverse("ventas:lista_ventas"))
        assert respuesta.status_code == 200
        assert respuesta.context["resumen"]["cantidad"] == 1
        assert respuesta.context["resumen"]["monto"] == Decimal("2490.00")

    def test_lista_ventas_otro_dia_vacia(self, client, vendedor, venta):
        client.force_login(vendedor)
        respuesta = client.get(reverse("ventas:lista_ventas"), {"fecha": "2000-01-01"})
        assert respuesta.context["resumen"]["cantidad"] == 0

    def test_lista_ventas_fecha_invalida_usa_hoy(self, client, vendedor, venta):
        client.force_login(vendedor)
        respuesta = client.get(reverse("ventas:lista_ventas"), {"fecha": "no-es-fecha"})
        assert respuesta.context["fecha"] == timezone.localdate()

    def test_detalle_venta_muestra_boton_anular_solo_a_admin(
        self, client, venta, admin, vendedor
    ):
        url = reverse("ventas:detalle_venta", args=[venta.pk])
        client.force_login(vendedor)
        assert "Anular venta" not in client.get(url).content.decode()
        client.force_login(admin)
        assert "Anular venta" in client.get(url).content.decode()

    def test_vendedor_recibe_403_al_anular(self, client, venta, vendedor):
        client.force_login(vendedor)
        respuesta = client.post(reverse("ventas:anular", args=[venta.pk]))
        assert respuesta.status_code == 403
        venta.refresh_from_db()
        assert venta.estado == EstadoVenta.VIGENTE

    def test_admin_anula_por_post(self, client, venta, admin):
        client.force_login(admin)
        respuesta = client.post(reverse("ventas:anular", args=[venta.pk]))
        assert respuesta.status_code == 302
        venta.refresh_from_db()
        assert venta.estado == EstadoVenta.ANULADA

    def test_admin_fuera_de_plazo_ve_mensaje(self, client, venta, admin):
        _envejecer(venta, 24 * 60)
        client.force_login(admin)
        respuesta = client.post(reverse("ventas:anular", args=[venta.pk]), follow=True)
        assert "ya no se puede anular" in respuesta.content.decode()
        assert "El plazo para anular esta venta ya venció" in respuesta.content.decode()
