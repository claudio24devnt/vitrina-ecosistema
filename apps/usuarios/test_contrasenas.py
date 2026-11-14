"""
Contraseñas: cambio propio, restablecimiento sin correo (administrador → vendedor,
operador → administrador) y recuperación por correo. Datos FICTICIOS.
"""

import logging
import re

import pytest
from django.core import mail
from django.core.cache import cache
from django.urls import reverse

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.servicios import crear_almacen
from apps.usuarios.models import RolUsuario, Usuario
from apps.usuarios.servicios import (
    MAX_CORREOS_RECUPERACION_POR_HORA,
    admitir_correo_de_recuperacion,
    puede_restablecer,
    restablecer_contrasena,
)

CLAVE_NUEVA = "mesón-nueva-2026"
CLAVE_ANTERIOR = "clave-de-prueba"  # la de conftest.poblar_almacen


@pytest.fixture(autouse=True)
def cache_limpia():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def operador(db):
    almacen = crear_almacen(
        razon_social="Operación Ficticia", rut="76000102-3", plan="operacion"
    )
    return Usuario.sin_aislamiento.create_user(
        email="operador@ficticio.test",
        nombre="Operador Ficticio",
        password=CLAVE_ANTERIOR,
        rol=RolUsuario.ADMIN,
        id_almacen=almacen,
        is_superuser=True,
        is_staff=True,
    )


def _recargar(usuario):
    return Usuario.sin_aislamiento.get(pk=usuario.pk)


# ---- Servicio ----------------------------------------------------------------------


@pytest.mark.django_db
class TestRestablecerContrasena:
    def test_administrador_a_su_vendedor(self, datos_a):
        restablecer_contrasena(
            autor=datos_a.admin, usuario=datos_a.vendedor, password=CLAVE_NUEVA
        )
        vendedor = _recargar(datos_a.vendedor)
        assert vendedor.check_password(CLAVE_NUEVA)
        assert not vendedor.check_password(CLAVE_ANTERIOR)

    def test_administrador_no_al_vendedor_de_otro_almacen(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError, match="No puedes"):
            restablecer_contrasena(
                autor=datos_a.admin, usuario=datos_b.vendedor, password=CLAVE_NUEVA
            )
        assert _recargar(datos_b.vendedor).check_password(CLAVE_ANTERIOR)

    def test_vendedor_no_puede(self, datos_a):
        assert not puede_restablecer(datos_a.vendedor, datos_a.admin)

    def test_nadie_a_si_mismo_ni_el_administrador_a_otro_administrador(self, datos_a, db):
        otro_admin = Usuario.sin_aislamiento.create_user(
            email="otro.admin@ficticio.test",
            nombre="Otro Admin Ficticio",
            password=CLAVE_ANTERIOR,
            rol=RolUsuario.ADMIN,
            id_almacen=datos_a.almacen,
        )
        assert not puede_restablecer(datos_a.admin, datos_a.admin)
        assert not puede_restablecer(datos_a.admin, otro_admin)

    def test_operador_a_administradores_de_clientes(self, datos_a, operador):
        assert puede_restablecer(operador, datos_a.admin)
        assert not puede_restablecer(operador, datos_a.vendedor)
        assert not puede_restablecer(operador, operador)

    def test_usuario_inactivo_no(self, datos_a):
        datos_a.vendedor.is_active = False
        assert not puede_restablecer(datos_a.admin, datos_a.vendedor)

    def test_contrasena_debil_no_cambia_nada(self, datos_a):
        with pytest.raises(ReglaDeNegocioError):
            restablecer_contrasena(
                autor=datos_a.admin, usuario=datos_a.vendedor, password="12345678"
            )
        assert _recargar(datos_a.vendedor).check_password(CLAVE_ANTERIOR)

    def test_queda_registro_sin_la_contrasena(self, datos_a, caplog):
        with caplog.at_level(logging.INFO, logger="tivoscanea.seguridad"):
            restablecer_contrasena(
                autor=datos_a.admin, usuario=datos_a.vendedor, password=CLAVE_NUEVA
            )
        texto = caplog.text
        assert f"usuario {datos_a.vendedor.pk}" in texto
        assert f"por usuario {datos_a.admin.pk}" in texto
        assert CLAVE_NUEVA not in texto


class TestTopeDeCorreos:
    def test_tope_por_hora_sin_distinguir_mayusculas(self):
        for _ in range(MAX_CORREOS_RECUPERACION_POR_HORA):
            assert admitir_correo_de_recuperacion("Alguien@Ficticio.Test")
        assert not admitir_correo_de_recuperacion("alguien@ficticio.test ")
        assert admitir_correo_de_recuperacion("otra.persona@ficticio.test")


# ---- Pantallas sin correo (fase 1) ---------------------------------------------------


@pytest.mark.django_db
class TestPantallaContrasenaVendedor:
    def _url(self, vendedor):
        return reverse("usuarios:contrasena_vendedor", args=[vendedor.pk])

    def test_la_lista_de_vendedores_ofrece_el_cambio(self, client, datos_a):
        client.force_login(datos_a.admin)
        html = client.get(reverse("usuarios:vendedores")).content.decode()
        assert self._url(datos_a.vendedor) in html

    def test_cambia_y_cierra_la_sesion_abierta_del_vendedor(self, client, datos_a):
        from django.test import Client

        caja_del_vendedor = Client()
        caja_del_vendedor.force_login(datos_a.vendedor)
        assert caja_del_vendedor.get(reverse("inicio")).status_code == 200

        client.force_login(datos_a.admin)
        respuesta = client.post(
            self._url(datos_a.vendedor),
            {"password": CLAVE_NUEVA, "password_repetida": CLAVE_NUEVA},
            follow=True,
        )
        assert "Contraseña de «Vendedor Ficticio A» cambiada" in respuesta.content.decode()
        assert _recargar(datos_a.vendedor).check_password(CLAVE_NUEVA)
        # La sesión que el vendedor tenía abierta deja de valer.
        assert caja_del_vendedor.get(reverse("inicio")).status_code == 302

    def test_errores_en_el_formulario(self, client, datos_a):
        client.force_login(datos_a.admin)
        html = client.post(
            self._url(datos_a.vendedor),
            {"password": CLAVE_NUEVA, "password_repetida": "otra"},
        ).content.decode()
        assert "Las contraseñas no coinciden." in html
        html = client.post(
            self._url(datos_a.vendedor), {"password": "123", "password_repetida": "123"}
        ).content.decode()
        assert "demasiado corta" in html
        assert _recargar(datos_a.vendedor).check_password(CLAVE_ANTERIOR)

    def test_vendedor_de_otro_almacen_no_existe(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        respuesta = client.post(
            self._url(datos_b.vendedor),
            {"password": CLAVE_NUEVA, "password_repetida": CLAVE_NUEVA},
        )
        assert respuesta.status_code == 404
        assert _recargar(datos_b.vendedor).check_password(CLAVE_ANTERIOR)

    def test_al_administrador_no_por_esta_via(self, client, datos_a):
        client.force_login(datos_a.admin)
        assert client.get(self._url(datos_a.admin)).status_code == 404

    def test_el_vendedor_no_entra(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        assert client.get(self._url(datos_a.vendedor)).status_code == 403


@pytest.mark.django_db
class TestPantallaContrasenaAdministrador:
    def _url(self, usuario):
        return reverse("almacenes:contrasena_administrador", args=[usuario.pk])

    def test_operador_ve_administradores_y_cambia_la_contrasena(
        self, client, operador, datos_a
    ):
        client.force_login(operador)
        html = client.get(reverse("almacenes:plataforma")).content.decode()
        assert self._url(datos_a.admin) in html
        assert self._url(operador) not in html

        client.post(
            self._url(datos_a.admin),
            {"password": CLAVE_NUEVA, "password_repetida": CLAVE_NUEVA},
        )
        assert _recargar(datos_a.admin).check_password(CLAVE_NUEVA)

    def test_operador_no_a_si_mismo_ni_a_vendedores(self, client, operador, datos_a):
        client.force_login(operador)
        assert client.get(self._url(operador)).status_code == 404
        assert client.get(self._url(datos_a.vendedor)).status_code == 404

    def test_un_administrador_no_entra(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        assert client.get(self._url(datos_b.admin)).status_code == 403


@pytest.mark.django_db
class TestCambiarMiContrasena:
    URL = "/cuentas/contrasena/"

    def test_menu_ofrece_el_cambio(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        assert self.URL in client.get(reverse("inicio")).content.decode()

    def test_contrasena_actual_equivocada(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        client.post(
            self.URL,
            {
                "old_password": "no-es-esta",
                "new_password1": CLAVE_NUEVA,
                "new_password2": CLAVE_NUEVA,
            },
        )
        assert _recargar(datos_a.vendedor).check_password(CLAVE_ANTERIOR)

    def test_cambia_y_sigue_con_la_sesion_abierta(self, client, datos_a):
        client.force_login(datos_a.vendedor)
        respuesta = client.post(
            self.URL,
            {
                "old_password": CLAVE_ANTERIOR,
                "new_password1": CLAVE_NUEVA,
                "new_password2": CLAVE_NUEVA,
            },
            follow=True,
        )
        assert "Tu contraseña quedó cambiada." in respuesta.content.decode()
        assert _recargar(datos_a.vendedor).check_password(CLAVE_NUEVA)
        assert client.get(reverse("inicio")).status_code == 200

    def test_sin_sesion_va_al_login(self, client):
        assert client.get(self.URL).status_code == 302


# ---- Recuperación por correo (fase 2) -------------------------------------------------


@pytest.mark.django_db
class TestRecuperarPorCorreo:
    URL = "/cuentas/recuperar/"

    @pytest.fixture(autouse=True)
    def con_correo(self, settings):
        settings.RECUPERACION_POR_CORREO = True

    def _enlace(self, correo):
        return re.search(r"https?://testserver(/cuentas/recuperar/\S+/)", correo.body).group(1)

    def test_login_ofrece_recuperar(self, client):
        assert self.URL in client.get(reverse("usuarios:login")).content.decode()

    def test_flujo_completo(self, client, datos_a):
        respuesta = client.post(self.URL, {"email": datos_a.vendedor.email.upper()})
        assert respuesta.status_code == 302
        assert len(mail.outbox) == 1
        correo = mail.outbox[0]
        assert correo.to == [datos_a.vendedor.email]
        assert "crea tu contraseña nueva" in correo.subject
        assert "Vendedor Ficticio A" in correo.body
        html, tipo = correo.alternatives[0]
        assert tipo == "text/html"
        assert f'href="http://testserver{self._enlace(correo)}"' in html

        enlace = self._enlace(correo)
        formulario = client.get(enlace, follow=True)
        assert "Crea tu contraseña nueva" in formulario.content.decode()
        url_formulario = formulario.redirect_chain[-1][0]
        listo = client.post(
            url_formulario,
            {"new_password1": CLAVE_NUEVA, "new_password2": CLAVE_NUEVA},
            follow=True,
        )
        assert "tu contraseña quedó cambiada" in listo.content.decode()
        assert _recargar(datos_a.vendedor).check_password(CLAVE_NUEVA)

        # El enlace sirve una sola vez.
        otra_vez = client.get(enlace, follow=True)
        assert "Este enlace ya no sirve" in otra_vez.content.decode()

    def test_correo_desconocido_responde_igual_y_no_envia(self, client, datos_a):
        respuesta = client.post(self.URL, {"email": "nadie@ficticio.test"})
        assert respuesta.status_code == 302
        assert respuesta.url == reverse("usuarios:recuperar_enviado")
        assert mail.outbox == []

    def test_usuario_inactivo_no_recibe(self, client, datos_a):
        Usuario.sin_aislamiento.filter(pk=datos_a.vendedor.pk).update(is_active=False)
        client.post(self.URL, {"email": datos_a.vendedor.email})
        assert mail.outbox == []

    def test_tope_de_correos_por_hora(self, client, datos_a):
        for _ in range(MAX_CORREOS_RECUPERACION_POR_HORA + 2):
            respuesta = client.post(self.URL, {"email": datos_a.vendedor.email})
            assert respuesta.url == reverse("usuarios:recuperar_enviado")
        assert len(mail.outbox) == MAX_CORREOS_RECUPERACION_POR_HORA

    def test_sin_correo_configurado_explica_a_quien_pedirla(self, client, datos_a, settings):
        settings.RECUPERACION_POR_CORREO = False
        html = client.get(self.URL).content.decode()
        assert "Pídele una nueva" in html
        assert "<form" not in html
        client.post(self.URL, {"email": datos_a.vendedor.email})
        assert mail.outbox == []
