"""
Backend de correo de Django que envía por Azure Communication Services (ACS) con la
identidad administrada del App Service: sin SMTP y sin clave guardada en ninguna parte.

Por qué no SMTP: el SMTP de ACS exige un registro de aplicación en Entra ID, y el
tenant de la universidad no deja crearlos. Por qué sin SDK: son dos llamadas HTTP
(token y envío) y cada dependencia hay que mantenerla cinco años (§12 del brief).

- Token: endpoint de identidad que App Service expone en IDENTITY_ENDPOINT /
  IDENTITY_HEADER, para el recurso https://communication.azure.com.
- Envío: POST {ACS_ENDPOINT}/emails:send (API 2023-03-31). ACS responde 202 y entrega
  después; el resultado final no se consulta.

Recursos en infra/modulos/correo.bicep.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

registro = logging.getLogger("tivoscanea.correo")

RECURSO_ACS = "https://communication.azure.com"
VERSION_API_ENVIO = "2023-03-31"
VERSION_API_IDENTIDAD = "2019-08-01"
PLAZO_SEGUNDOS = 10
# El token se renueva 5 minutos antes de vencer.
MARGEN_RENOVACION_SEGUNDOS = 300


class ErrorCorreoACS(Exception):
    pass


_token = {"valor": None, "vence": 0.0}
_candado = threading.Lock()


def _pedir_json(solicitud):
    try:
        with urllib.request.urlopen(solicitud, timeout=PLAZO_SEGUNDOS) as respuesta:
            cuerpo = respuesta.read()
            return respuesta.status, (json.loads(cuerpo) if cuerpo else {})
    except urllib.error.HTTPError as error:
        detalle = error.read()[:300].decode("utf-8", "replace")
        raise ErrorCorreoACS(f"HTTP {error.code}: {detalle}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise ErrorCorreoACS(f"Sin respuesta: {error}") from None


def obtener_token():
    """Token de la identidad administrada, guardado hasta poco antes de que venza."""
    with _candado:
        if _token["valor"] and time.time() < _token["vence"] - MARGEN_RENOVACION_SEGUNDOS:
            return _token["valor"]
        endpoint = os.environ.get("IDENTITY_ENDPOINT")
        cabecera = os.environ.get("IDENTITY_HEADER")
        if not endpoint or not cabecera:
            raise ErrorCorreoACS("Sin identidad administrada (IDENTITY_ENDPOINT vacío).")
        consulta = urllib.parse.urlencode(
            {"resource": RECURSO_ACS, "api-version": VERSION_API_IDENTIDAD}
        )
        solicitud = urllib.request.Request(
            f"{endpoint}?{consulta}", headers={"X-IDENTITY-HEADER": cabecera}
        )
        _, datos = _pedir_json(solicitud)
        _token["valor"] = datos["access_token"]
        _token["vence"] = float(datos["expires_on"])
        return _token["valor"]


def _cuerpo_envio(mensaje):
    _, remitente = parseaddr(mensaje.from_email or settings.DEFAULT_FROM_EMAIL)
    destinatarios = {
        campo: [{"address": parseaddr(d)[1]} for d in getattr(mensaje, campo)]
        for campo in ("to", "cc", "bcc")
        if getattr(mensaje, campo)
    }
    contenido = {"subject": mensaje.subject, "plainText": mensaje.body}
    for alternativa, tipo in getattr(mensaje, "alternatives", []):
        if tipo == "text/html":
            contenido["html"] = alternativa
    return {
        "senderAddress": remitente,
        "recipients": destinatarios,
        "content": contenido,
        "userEngagementTrackingDisabled": True,
    }


class CorreoACSBackend(BaseEmailBackend):
    """Usar con EMAIL_BACKEND = "tivoscanea.correo_acs.CorreoACSBackend" y ACS_ENDPOINT."""

    def send_messages(self, email_messages):
        enviados = 0
        for mensaje in email_messages:
            if not mensaje.recipients():
                continue
            try:
                self._enviar(mensaje)
            except ErrorCorreoACS:
                if not self.fail_silently:
                    raise
                registro.exception("No se pudo enviar un correo por ACS")
            else:
                enviados += 1
        return enviados

    def _enviar(self, mensaje):
        url = (
            f"{settings.ACS_ENDPOINT.rstrip('/')}/emails:send?api-version={VERSION_API_ENVIO}"
        )
        solicitud = urllib.request.Request(
            url,
            data=json.dumps(_cuerpo_envio(mensaje)).encode(),
            headers={
                "Authorization": f"Bearer {obtener_token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        estado, _ = _pedir_json(solicitud)
        if estado != 202:
            raise ErrorCorreoACS(f"Respuesta inesperada de ACS: HTTP {estado}")
