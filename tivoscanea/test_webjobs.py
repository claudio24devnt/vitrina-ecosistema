"""
WebJobs de App Service (1.6): cada job programado existe, tiene un horario NCRONTAB
válido, llama a un comando de manage.py que existe, y su script es ejecutable y con
finales de línea LF (con CRLF, bash en Linux falla con «$'\\r': command not found»).
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import get_commands

RAIZ = Path(__file__).resolve().parent.parent
JOBS = RAIZ / "App_Data" / "jobs" / "triggered"
LANZADOR = RAIZ / "scripts" / "webjob.sh"
ESPERADOS = {
    "alertar-stock-bajo": "alertar_stock_bajo",
    "avisar-cierre-mes": "avisar_cierre_mes",
}


def test_estan_los_jobs_esperados():
    assert {d.name for d in JOBS.iterdir() if d.is_dir()} == set(ESPERADOS)


@pytest.mark.parametrize("job, comando", ESPERADOS.items())
def test_job_bien_formado(job, comando):
    carpeta = JOBS / job
    horario = json.loads((carpeta / "settings.job").read_text(encoding="utf-8"))["schedule"]
    campos = horario.split()
    assert len(campos) == 6, "NCRONTAB lleva seis campos: segundo primero"
    assert all(re.fullmatch(r"[\d*/,-]+", campo) for campo in campos)

    run = (carpeta / "run.sh").read_bytes()
    assert b"\r" not in run
    assert run.startswith(b"#!/bin/bash\n")
    assert run.decode().split()[-1] == comando
    assert comando in get_commands()


def test_scripts_ejecutables_y_con_lf_en_git():
    rutas = [LANZADOR, *JOBS.glob("*/run.sh")]
    assert b"\r" not in LANZADOR.read_bytes()
    if not shutil.which("git"):
        pytest.skip("git no está disponible")
    salida = subprocess.run(
        ["git", "ls-files", "-s", "--", *[str(r.relative_to(RAIZ)) for r in rutas]],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    ).stdout
    modos = dict(
        (linea.split()[3], linea.split()[0]) for linea in salida.splitlines() if linea
    )
    assert len(modos) == len(rutas), salida
    assert set(modos.values()) == {"100755"}


@pytest.mark.skipif(sys.platform == "win32", reason="en Windows «bash» puede ser el de WSL")
class TestLanzador:
    def _app_falsa(self, raiz):
        app = raiz / "app"
        binarios = app / "antenv" / "bin"
        binarios.mkdir(parents=True)
        (app / "manage.py").touch()
        (binarios / "activate").write_text(f'export PATH="{binarios}:$PATH"\n')
        python = binarios / "python"
        python.write_text('#!/bin/bash\necho "PYTHON $PWD $*"\n')
        python.chmod(0o755)
        return app

    def _correr(self, raices, *argumentos):
        entorno = {**os.environ, "TIVOSCANEA_RAICES": raices}
        return subprocess.run(
            ["bash", str(LANZADOR), *argumentos], env=entorno, capture_output=True, text=True
        )

    def test_encuentra_la_app_y_su_entorno(self, tmp_path):
        app = self._app_falsa(tmp_path)
        (tmp_path / "vacia").mkdir()
        resultado = self._correr(f"{tmp_path / 'vacia'} {app}/", "alertar_stock_bajo")
        assert resultado.returncode == 0, resultado.stderr
        assert (
            resultado.stdout.splitlines()[-1] == f"PYTHON {app} manage.py alertar_stock_bajo"
        )

    def test_sin_app_falla_con_mensaje(self, tmp_path):
        resultado = self._correr(str(tmp_path), "alertar_stock_bajo")
        assert resultado.returncode == 1
        assert "no se encontró manage.py" in resultado.stderr
