"""
Verificación rápida de producción antes de una demostración (docs/PLAN_PRESENTACION.md).
Sólo páginas públicas: no inicia sesión ni toca datos.

    python scripts/verificar_produccion.py
    python scripts/verificar_produccion.py --host https://otra-app.azurewebsites.net

Revisa salud, login, estáticos, recuperación por correo y vigencia del certificado,
con el tiempo de cada una. Sale con código 1 si algo falla.
"""

import argparse
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

HOST_POR_DEFECTO = "https://app-tivoscanea-nppckr.azurewebsites.net"
LENTO_MS = 2000  # el mismo umbral del p95 de la caja (§6)


def pedir(url):
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=30) as respuesta:
            cuerpo = respuesta.read().decode("utf-8", "replace")
            estado = respuesta.status
    except urllib.error.HTTPError as error:
        cuerpo, estado = "", error.code
    except (urllib.error.URLError, TimeoutError) as error:
        return None, f"sin respuesta ({error})", (time.perf_counter() - inicio) * 1000
    return estado, cuerpo, (time.perf_counter() - inicio) * 1000


def dias_de_certificado(host):
    nombre = urlparse(host).hostname
    contexto = ssl.create_default_context()
    with socket.create_connection((nombre, 443), timeout=15) as conexion:
        with contexto.wrap_socket(conexion, server_hostname=nombre) as tls:
            vence = tls.getpeercert()["notAfter"]
    fecha = datetime.strptime(vence, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (fecha - datetime.now(timezone.utc)).days


def main():
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    argumentos.add_argument("--host", default=HOST_POR_DEFECTO)
    host = argumentos.parse_args().host.rstrip("/")

    problemas = []

    def revisar(nombre, ruta, debe_contener=None):
        estado, cuerpo, ms = pedir(host + ruta)
        bien = estado == 200 and (debe_contener is None or debe_contener in cuerpo)
        aviso = "" if ms < LENTO_MS else "  (LENTO)"
        print(f"{'OK ' if bien else 'MAL'} {nombre:28} {ms:6.0f} ms  HTTP {estado}{aviso}")
        if not bien:
            problemas.append(nombre)
        return cuerpo if bien else ""

    print(f"Verificando {host}\n")
    revisar("Salud (/salud/)", "/salud/", "ok")
    login = revisar("Pantalla de ingreso", "/cuentas/login/", "TivoScanea")
    for estatico in sorted(set(re.findall(r'/static/[^"]+\.(?:css|js)', login))):
        revisar(f"Estático {estatico.split('/')[-1][:20]}", estatico)
    revisar("Recuperar por correo", "/cuentas/recuperar/", "Enviar enlace")

    try:
        dias = dias_de_certificado(host)
        bien = dias > 7
        print(f"{'OK ' if bien else 'MAL'} {'Certificado HTTPS':28} vence en {dias} días")
        if not bien:
            problemas.append("certificado")
    except (OSError, ssl.SSLError) as error:
        print(f"MAL {'Certificado HTTPS':28} {error}")
        problemas.append("certificado")

    if problemas:
        print(f"\nFALLA: {', '.join(problemas)}. Ver docs/PLAN_PRESENTACION.md (plan B).")
        return 1
    print("\nTodo bien. Ingresa una vez como administrador y como vendedor para calentar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
