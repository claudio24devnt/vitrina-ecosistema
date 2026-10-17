"""
Publica los WebJobs de webjobs/ en el App Service con la API de Kudu (1.6).

No viajan dentro del paquete de la aplicación: la compilación de App Service (Oryx)
comprime el código en output.tar.zst y Kudu no ve App_Data/jobs. Cada job se sube
como un zip autocontenido (run.sh, settings.job y el lanzador scripts/webjob.sh).
Se corre después de cada despliegue del código; publicar dos veces lo reemplaza.

    python scripts/publicar_webjobs.py <nombre-app>

Usa la sesión de Azure CLI (`az login`, o azure/login en GitHub Actions). Sólo
biblioteca estándar: corre igual en el runner y en Windows.
"""

import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_JOBS = RAIZ / "webjobs"
LANZADOR = RAIZ / "scripts" / "webjob.sh"


def jobs():
    return sorted(d for d in CARPETA_JOBS.iterdir() if (d / "run.sh").is_file())


def _agregar(zip_, nombre, datos, ejecutable):
    info = zipfile.ZipInfo(nombre)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100755 if ejecutable else 0o100644) << 16
    # En Linux un CRLF rompe bash («$'\r': command not found»).
    zip_.writestr(info, datos.replace(b"\r\n", b"\n"))


def empaquetar(carpeta):
    """Zip del job: run.sh, settings.job y webjob.sh en la raíz, con LF y +x."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_:
        _agregar(zip_, "run.sh", (carpeta / "run.sh").read_bytes(), True)
        _agregar(zip_, "settings.job", (carpeta / "settings.job").read_bytes(), False)
        _agregar(zip_, "webjob.sh", LANZADOR.read_bytes(), True)
    return buffer.getvalue()


def _az():
    return os.environ.get("AZ") or shutil.which("az") or shutil.which("az.cmd") or "az"


def _token():
    resultado = subprocess.run(
        [_az(), "account", "get-access-token", "--query", "accessToken", "-o", "tsv"],
        capture_output=True,
        text=True,
        check=True,
    )
    return resultado.stdout.strip()


def publicar(app, carpeta, token):
    url = f"https://{app}.scm.azurewebsites.net/api/triggeredwebjobs/{carpeta.name}"
    solicitud = urllib.request.Request(
        url,
        data=empaquetar(carpeta),
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/zip",
            "Content-Disposition": f"attachment; filename={carpeta.name}.zip",
        },
    )
    with urllib.request.urlopen(solicitud, timeout=120) as respuesta:
        return respuesta.status


def main(argumentos):
    if len(argumentos) != 1:
        print(__doc__)
        return 2
    app = argumentos[0]
    token = _token()
    for carpeta in jobs():
        estado = publicar(app, carpeta, token)
        print(f"{carpeta.name}: HTTP {estado}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
