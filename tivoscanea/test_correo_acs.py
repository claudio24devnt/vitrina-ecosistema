"""
Backend de correo por Azure Communication Services. Sin red: se simula urlopen.
Direcciones FICTICIAS.
"""

import io
import json
import time
import urllib.error
from unittest import mock

import pytest
from django.core.mail import EmailMultiAlternatives, EmailMessage

from tivoscanea import correo_acs

ENDPOINT = "https://acs-ficticio.brazil.communication.azure.com"
REMITENTE = "TivoScanea <DoNotReply@ficticio.azurecomm.net>"


class Respuesta:
    def __init__(self, estado, datos=None):
        self.status = estado
        self._cuerpo = json.dumps(datos).encode() if datos is not None else b""

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def entorno(settings, monkeypatch):
    settings.ACS_ENDPOINT = ENDPOINT
    settings.DEFAULT_FROM_EMAIL = REMITENTE
    settings.EMAIL_BACKEND = "tivoscanea.correo_acs.CorreoACSBackend"
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identidad.ficticia/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "cabecera-ficticia")
    correo_acs._token.update(valor=None, vence=0.0)


def _urlopen(solicitudes, respuesta_envio=None):
    """Simula el endpoint de identidad y el de envío, guardando cada solicitud."""

    def falso(solicitud, timeout):
        solicitudes.append(solicitud)
        assert timeout == correo_acs.PLAZO_SEGUNDOS
        if solicitud.full_url.startswith("http://identidad.ficticia"):
            return Respuesta(
                200, {"access_token": "token-ficticio", "expires_on": str(time.time() + 3600)}
            )
        if respuesta_envio is not None:
            return respuesta_envio(solicitud)
        return Respuesta(202, {"id": "operacion-ficticia", "status": "Running"})

    return falso


def _mensaje(**cambios):
    datos = {
        "subject": "Asunto ficticio",
        "body": "Cuerpo ficticio",
        "to": ["Vendedora <vendedora@ficticio.test>"],
    }
    datos.update(cambios)
    return EmailMessage(**datos)


def test_envia_con_token_de_la_identidad_administrada():
    solicitudes = []
    with mock.patch("urllib.request.urlopen", _urlopen(solicitudes)):
        assert _mensaje().send() == 1

    identidad, envio = solicitudes
    assert "resource=https%3A%2F%2Fcommunication.azure.com" in identidad.full_url
    assert identidad.get_header("X-identity-header") == "cabecera-ficticia"

    assert envio.full_url == f"{ENDPOINT}/emails:send?api-version=2023-03-31"
    assert envio.get_header("Authorization") == "Bearer token-ficticio"
    cuerpo = json.loads(envio.data)
    assert cuerpo["senderAddress"] == "DoNotReply@ficticio.azurecomm.net"
    assert cuerpo["recipients"] == {"to": [{"address": "vendedora@ficticio.test"}]}
    assert cuerpo["content"] == {"subject": "Asunto ficticio", "plainText": "Cuerpo ficticio"}
    assert cuerpo["userEngagementTrackingDisabled"] is True


def test_reutiliza_el_token_mientras_no_venza():
    solicitudes = []
    with mock.patch("urllib.request.urlopen", _urlopen(solicitudes)):
        _mensaje().send()
        _mensaje().send()
    identidades = [s for s in solicitudes if "identidad.ficticia" in s.full_url]
    assert len(identidades) == 1


def test_incluye_html_y_copias():
    solicitudes = []
    mensaje = EmailMultiAlternatives(
        "Asunto", "Texto", to=["a@ficticio.test"], bcc=["b@ficticio.test"]
    )
    mensaje.attach_alternative("<p>Texto</p>", "text/html")
    with mock.patch("urllib.request.urlopen", _urlopen(solicitudes)):
        mensaje.send()
    cuerpo = json.loads(solicitudes[-1].data)
    assert cuerpo["content"]["html"] == "<p>Texto</p>"
    assert cuerpo["recipients"]["bcc"] == [{"address": "b@ficticio.test"}]


def test_error_de_acs_se_informa():
    def rechazo(solicitud):
        raise urllib.error.HTTPError(
            solicitud.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"limite")
        )

    with mock.patch("urllib.request.urlopen", _urlopen([], rechazo)):
        with pytest.raises(correo_acs.ErrorCorreoACS, match="HTTP 429"):
            _mensaje().send()
        assert _mensaje().send(fail_silently=True) == 0


def test_sin_identidad_administrada(monkeypatch):
    monkeypatch.delenv("IDENTITY_ENDPOINT")
    with pytest.raises(correo_acs.ErrorCorreoACS, match="identidad administrada"):
        _mensaje().send()


@pytest.mark.django_db
def test_si_el_envio_falla_la_recuperacion_responde_igual(client, datos_a, settings):
    from django.core.cache import cache
    from django.urls import reverse

    cache.clear()
    settings.RECUPERACION_POR_CORREO = True
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("caído")):
        respuesta = client.post("/cuentas/recuperar/", {"email": datos_a.vendedor.email})
    assert respuesta.status_code == 302
    assert respuesta.url == reverse("usuarios:recuperar_enviado")
