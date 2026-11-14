"""
Límite de intentos de ingreso fallidos (OWASP A07). Datos FICTICIOS.
"""

import pytest
from django.test import RequestFactory
from django.urls import reverse

from apps.usuarios.servicios import (
    MAX_INGRESOS_FALLIDOS_POR_CORREO,
    MAX_INGRESOS_FALLIDOS_POR_IP,
    ingreso_bloqueado,
    ip_del_cliente,
    registrar_ingreso_fallido,
    restablecer_contrasena,
)

CLAVE = "clave-de-prueba"  # la de conftest.poblar_almacen
URL = "/cuentas/login/"


def _ingresar(client, email, clave, **extra):
    return client.post(URL, {"username": email, "password": clave}, **extra)


class TestIpDelCliente:
    @pytest.mark.parametrize(
        "cabeceras, esperada",
        [
            ({"HTTP_X_FORWARDED_FOR": "200.1.2.3:51234"}, "200.1.2.3"),
            # La primera la puede inventar el cliente; la última la pone App Service.
            ({"HTTP_X_FORWARDED_FOR": "1.1.1.1, 200.1.2.3:443"}, "200.1.2.3"),
            ({"HTTP_X_FORWARDED_FOR": "[2800:150::1]:4000"}, "2800:150::1"),
            ({"REMOTE_ADDR": "10.0.0.5"}, "10.0.0.5"),
        ],
    )
    def test_formatos(self, cabeceras, esperada):
        solicitud = RequestFactory().get("/", **cabeceras)
        if "REMOTE_ADDR" not in cabeceras:
            solicitud.META["REMOTE_ADDR"] = "169.254.0.1"
        assert ip_del_cliente(solicitud) == esperada


class TestContadores:
    def test_bloqueo_por_correo_sin_distinguir_mayusculas(self):
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO - 1):
            registrar_ingreso_fallido("Alguien@Ficticio.Test", "200.0.0.1")
        assert not ingreso_bloqueado("alguien@ficticio.test", "200.0.0.2")
        registrar_ingreso_fallido("alguien@ficticio.test", "200.0.0.1")
        assert ingreso_bloqueado("ALGUIEN@ficticio.test", "200.0.0.9")
        assert not ingreso_bloqueado("otra@ficticio.test", "200.0.0.9")

    def test_bloqueo_por_ip_aunque_cambie_el_correo(self):
        for i in range(MAX_INGRESOS_FALLIDOS_POR_IP):
            registrar_ingreso_fallido(f"cuenta{i}@ficticio.test", "200.0.0.7")
        assert ingreso_bloqueado("nueva@ficticio.test", "200.0.0.7")
        assert not ingreso_bloqueado("nueva@ficticio.test", "200.0.0.8")


@pytest.mark.django_db
class TestPantallaIngreso:
    def test_bloquea_tras_cinco_fallos_aun_con_la_clave_correcta(self, client, datos_a):
        email = datos_a.vendedor.email
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO):
            html = _ingresar(client, email, "no-es-esta").content.decode()
            assert "no son correctos" in html
        respuesta = _ingresar(client, email, CLAVE)
        assert respuesta.status_code == 200
        assert "demasiados intentos fallidos" in respuesta.content.decode()

    def test_ingresar_bien_reinicia_el_contador(self, client, datos_a):
        email = datos_a.vendedor.email
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO - 1):
            _ingresar(client, email, "no-es-esta")
        assert _ingresar(client, email, CLAVE).status_code == 302
        client.logout()
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO - 1):
            _ingresar(client, email, "no-es-esta")
        assert _ingresar(client, email, CLAVE).status_code == 302

    def test_otra_cuenta_no_queda_bloqueada(self, client, datos_a):
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO):
            _ingresar(client, datos_a.vendedor.email, "no-es-esta")
        assert _ingresar(client, datos_a.admin.email, CLAVE).status_code == 302

    def test_la_ip_que_prueba_muchas_cuentas_queda_bloqueada(self, client, datos_a):
        ip = {"HTTP_X_FORWARDED_FOR": "200.9.9.9:1234"}
        for i in range(MAX_INGRESOS_FALLIDOS_POR_IP):
            _ingresar(client, f"cuenta{i}@ficticio.test", "x", **ip)
        bloqueada = _ingresar(client, datos_a.admin.email, CLAVE, **ip)
        assert "demasiados intentos fallidos" in bloqueada.content.decode()
        otra_ip = {"HTTP_X_FORWARDED_FOR": "200.9.9.10:1234"}
        assert _ingresar(client, datos_a.admin.email, CLAVE, **otra_ip).status_code == 302

    def test_restablecer_la_contrasena_quita_el_bloqueo(self, client, datos_a):
        email = datos_a.vendedor.email
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO):
            _ingresar(client, email, "no-es-esta")
        restablecer_contrasena(
            autor=datos_a.admin, usuario=datos_a.vendedor, password="mesón-nueva-2026"
        )
        assert _ingresar(client, email, "mesón-nueva-2026").status_code == 302

    def test_el_login_ofrece_recuperar_al_bloquear(self, client, datos_a):
        for _ in range(MAX_INGRESOS_FALLIDOS_POR_CORREO + 1):
            respuesta = _ingresar(client, datos_a.vendedor.email, "no-es-esta")
        assert reverse("usuarios:recuperar") in respuesta.content.decode()
