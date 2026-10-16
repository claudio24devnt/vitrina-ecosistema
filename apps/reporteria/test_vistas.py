"""
Integración y sistema: pantalla y API del reporte mensual (CU-04), alertas en el
panel y comandos programados (CU-05, cierre de mes). Datos FICTICIOS.
"""

from datetime import date
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.reporteria.models import AccesoReporte, Alerta, TipoAlerta
from apps.reporteria.servicios import alertar_stock_bajo, hoy_local, mes_anterior, primer_dia
from apps.reporteria.test_servicios import dar_de_alta_en, local, producto_ficticio, vender
from conftest import usuario_de

URL_REPORTE = "/reportes/mensual/"
URL_API = "/api/reportes/mensual/"


@pytest.fixture
def tienda(almacen):
    return dar_de_alta_en(almacen, date(2026, 1, 1))


@pytest.fixture
def admin(tienda):
    return usuario_de(tienda)


@pytest.fixture
def con_ventas_en_septiembre(tienda):
    producto = producto_ficticio(tienda, "Pan Amasado Ficticio", precio=250)
    vender(tienda, local(2026, 9, 7, 8, 30), (producto, 4))
    vender(tienda, local(2026, 9, 8, 19, 0), (producto, 2))
    return producto


@pytest.mark.django_db
class TestPantallaReporte:
    def test_vendedor_no_ve_reportes(self, client, tienda):
        client.force_login(usuario_de(tienda, "vendedor"))
        assert client.get(URL_REPORTE).status_code == 403
        assert AccesoReporte.objects.del_almacen(tienda).count() == 0

    def test_admin_ve_el_reporte_del_mes_y_queda_registrado(
        self, client, tienda, admin, con_ventas_en_septiembre
    ):
        client.force_login(admin)
        respuesta = client.get(URL_REPORTE, {"mes": "2026-09"})
        assert respuesta.status_code == 200
        html = respuesta.content.decode()
        assert "Reporte de septiembre 2026" in html
        assert "Pan Amasado Ficticio" in html
        assert "$1.500" in html  # total del mes
        assert "No hay ventas registradas en agosto 2026 para comparar." in html
        acceso = AccesoReporte.objects.del_almacen(tienda).get()
        assert (acceso.id_usuario, acceso.mes_consultado) == (admin, date(2026, 9, 1))

    def test_mes_sin_ventas_lo_dice_en_vez_de_mostrar_tablas_vacias(self, client, admin):
        client.force_login(admin)
        html = client.get(URL_REPORTE, {"mes": "2026-08"}).content.decode()
        assert "No hay ventas registradas en agosto 2026." in html
        assert "Productos más vendidos" not in html

    def test_por_omision_muestra_el_ultimo_mes_cerrado(self, client, admin):
        client.force_login(admin)
        respuesta = client.get(URL_REPORTE, {"mes": "cualquier-cosa"})
        assert respuesta.context["reporte"].mes == mes_anterior(primer_dia(hoy_local()))

    def test_mes_futuro_vuelve_con_un_mensaje(self, client, admin):
        client.force_login(admin)
        respuesta = client.get(URL_REPORTE, {"mes": "2999-01"}, follow=True)
        assert "todavía no empieza" in respuesta.content.decode()

    def test_el_selector_ofrece_los_meses_desde_el_inicio(self, client, tienda, admin):
        client.force_login(admin)
        meses = client.get(URL_REPORTE).context["meses"]
        assert meses[-1] == (date(2026, 1, 1), "Enero 2026")
        assert meses[0][0] == primer_dia(hoy_local())


@pytest.mark.django_db
class TestAPIReporte:
    def test_admin_recibe_el_reporte_en_json(
        self, client, tienda, admin, con_ventas_en_septiembre
    ):
        client.force_login(admin)
        respuesta = client.get(URL_API, {"mes": "2026-09"})
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["hay_ventas"] is True
        assert datos["cantidad_ventas"] == 2
        assert datos["mas_vendidos"][0]["nombre"] == "Pan Amasado Ficticio"
        assert [f["cantidad"] for f in datos["por_franja"]] == [1, 0, 0, 1, 0]
        assert datos["variacion"] is None and datos["motivo_sin_comparacion"]
        assert AccesoReporte.objects.del_almacen(tienda).count() == 1

    def test_vendedor_no_tiene_acceso(self, client, tienda):
        client.force_login(usuario_de(tienda, "vendedor"))
        assert client.get(URL_API, {"mes": "2026-09"}).status_code == 403

    def test_sin_sesion_no_tiene_acceso(self, client, tienda):
        assert client.get(URL_API, {"mes": "2026-09"}).status_code == 403

    @pytest.mark.parametrize("mes", ["", "2026-13", "septiembre", "2999-01"])
    def test_mes_invalido_o_futuro(self, client, admin, mes):
        client.force_login(admin)
        respuesta = client.get(URL_API, {"mes": mes})
        assert respuesta.status_code == 400
        assert respuesta.json()["detalle"]


@pytest.mark.django_db
class TestAlertasEnElPanel:
    @pytest.fixture
    def alerta(self, tienda):
        producto_ficticio(tienda, "Leche Ficticia", stock_actual=1, stock_minimo=3)
        return alertar_stock_bajo(tienda)[0]

    def test_admin_ve_la_alerta_y_la_da_por_vista(self, client, admin, alerta):
        client.force_login(admin)
        html = client.get(reverse("inicio")).content.decode()
        assert alerta.mensaje in html
        assert "?stock_bajo=1" in html

        respuesta = client.post(reverse("reporteria:marcar_vista", args=[alerta.pk]))
        assert respuesta.status_code == 302
        alerta.refresh_from_db()
        assert alerta.id_usuario_vista == admin
        assert alerta.mensaje not in client.get(reverse("inicio")).content.decode()

    def test_vendedor_no_ve_alertas_ni_puede_marcarlas(self, client, tienda, alerta):
        client.force_login(usuario_de(tienda, "vendedor"))
        assert alerta.mensaje not in client.get(reverse("inicio")).content.decode()
        url = reverse("reporteria:marcar_vista", args=[alerta.pk])
        assert client.post(url).status_code == 403

    def test_no_se_marca_una_alerta_de_otro_almacen(self, client, datos_b, alerta):
        client.force_login(datos_b.admin)
        url = reverse("reporteria:marcar_vista", args=[alerta.pk])
        assert client.post(url).status_code == 404
        alerta.refresh_from_db()
        assert alerta.fecha_vista is None

    def test_marcar_exige_post(self, client, admin, alerta):
        client.force_login(admin)
        url = reverse("reporteria:marcar_vista", args=[alerta.pk])
        assert client.get(url).status_code == 405

    def test_aviso_de_cierre_lleva_al_reporte_del_mes(
        self, client, tienda, admin, con_ventas_en_septiembre
    ):
        call_command("avisar_cierre_mes", "--fecha", "2026-10-01", stdout=StringIO())
        client.force_login(admin)
        html = client.get(reverse("inicio")).content.decode()
        assert "Ya está disponible el reporte de septiembre 2026." in html
        assert f"{URL_REPORTE}?mes=2026-09" in html
        client.get(URL_REPORTE, {"mes": "2026-09"})
        assert "Ya está disponible" not in client.get(reverse("inicio")).content.decode()


@pytest.mark.django_db
class TestComandos:
    def test_alertar_stock_bajo_recorre_los_almacenes(self, tienda, datos_b):
        producto_ficticio(tienda, stock_actual=0, stock_minimo=1)
        datos_b.producto.stock_actual = 50
        datos_b.producto.save(update_fields=["stock_actual"])
        salida = StringIO()
        call_command("alertar_stock_bajo", "--fecha", "2026-10-16", stdout=salida)
        texto = salida.getvalue()
        assert "alerta creada: Hay 1 producto con stock bajo el mínimo" in texto
        assert "sin productos bajo el mínimo, no se genera alerta" in texto
        alertas = Alerta.objects.del_almacen(tienda).filter(tipo=TipoAlerta.STOCK_BAJO)
        assert alertas.get().fecha_referencia == date(2026, 10, 16)

    def test_alertar_stock_bajo_dos_veces_no_duplica(self, tienda):
        producto_ficticio(tienda, stock_actual=0, stock_minimo=1)
        call_command("alertar_stock_bajo", "--fecha", "2026-10-16", stdout=StringIO())
        salida = StringIO()
        call_command("alertar_stock_bajo", "--fecha", "2026-10-16", stdout=salida)
        assert "la alerta de hoy ya existía" in salida.getvalue()
        assert Alerta.objects.del_almacen(tienda).count() == 1

    def test_almacen_inactivo_no_se_revisa(self, tienda):
        producto_ficticio(tienda, stock_actual=0, stock_minimo=1)
        tienda.activo = False
        tienda.save(update_fields=["activo"])
        salida = StringIO()
        call_command("alertar_stock_bajo", stdout=salida)
        assert salida.getvalue() == ""

    def test_avisar_cierre_mes_sin_ventas(self, tienda):
        salida = StringIO()
        call_command("avisar_cierre_mes", "--fecha", "2026-10-01", stdout=salida)
        assert "no tuvo ventas" in salida.getvalue()
        assert not Alerta.objects.del_almacen(tienda).exists()

    @pytest.mark.parametrize("comando", ["alertar_stock_bajo", "avisar_cierre_mes"])
    def test_fecha_mal_escrita(self, tienda, comando):
        with pytest.raises(CommandError, match="AAAA-MM-DD"):
            call_command(comando, "--fecha", "16-10-2026")
