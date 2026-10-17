"""
La configuración de producción pasa `check --deploy` (lo que corre App Service al
arrancar) y la del CI no. Se prueba en un proceso aparte porque settings.py se lee
una sola vez, con las variables de entorno del momento.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Clave inventada para la prueba: larga y variada como la que genera Django.
CLAVE_FICTICIA = "prueba-produccion-" + "x7Kq#2mZ!pL9@wR4$vN8^bT3&yH6*cF1" * 2

PRODUCCION = {
    "DJANGO_SECRET_KEY": CLAVE_FICTICIA,
    "DJANGO_DEBUG": "False",
    "DJANGO_PRODUCCION": "True",
    "DJANGO_ALLOWED_HOSTS": "app-ficticia.azurewebsites.net",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.ficticio.test",
    "DB_SSLMODE": "require",
}


# Avisos que dependen del dominio definitivo (aún no elegido): HSTS para subdominios
# y la lista de precarga de los navegadores. Se deciden al tener el dominio.
AVISOS_PENDIENTES_DEL_DOMINIO = {"security.W005", "security.W021"}


def _manage(*argumentos, **variables):
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", **variables}
    return subprocess.run(
        [sys.executable, "manage.py", *argumentos],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _leer(nombre, **variables):
    codigo = f"from django.conf import settings; print(repr(settings.{nombre}))"
    resultado = _manage("shell", "--no-imports", "-c", codigo, **variables)
    assert resultado.returncode == 0, resultado.stderr
    return resultado.stdout.strip()


def test_produccion_pasa_check_deploy():
    resultado = _manage("check", "--deploy", "--fail-level", "ERROR", **PRODUCCION)
    assert resultado.returncode == 0, resultado.stderr


def test_produccion_solo_deja_los_avisos_que_dependen_del_dominio():
    resultado = _manage("check", "--deploy", **PRODUCCION)
    salida = resultado.stdout + resultado.stderr
    avisos = set(re.findall(r"\((security\.W\d+|tivoscanea\.\w+)\)", salida))
    assert avisos == AVISOS_PENDIENTES_DEL_DOMINIO, salida


def test_debug_false_en_texto_queda_desactivado():
    # Regresión: env("DJANGO_DEBUG") devolvía la cadena "False", que es verdadera.
    assert _leer("DEBUG", **PRODUCCION) == "False"


def test_la_clave_del_ci_bloquea_el_arranque():
    variables = {**PRODUCCION, "DJANGO_SECRET_KEY": "ci-only-not-a-secret-do-not-reuse"}
    resultado = _manage("check", "--deploy", "--fail-level", "ERROR", **variables)
    assert resultado.returncode != 0
    assert "tivoscanea.E001" in resultado.stderr


@pytest.mark.parametrize(
    "nombre, esperado",
    [
        ("SESSION_COOKIE_SECURE", "True"),
        ("CSRF_COOKIE_SECURE", "True"),
        ("SECURE_PROXY_SSL_HEADER", "('HTTP_X_FORWARDED_PROTO', 'https')"),
        ("CSRF_TRUSTED_ORIGINS", "['https://app.ficticio.test']"),
        ("DATABASES['default']['OPTIONS']", "{'sslmode': 'require'}"),
    ],
)
def test_valores_de_produccion(nombre, esperado):
    assert _leer(nombre, **PRODUCCION) == esperado


def test_desarrollo_no_exige_https():
    variables = {**PRODUCCION, "DJANGO_PRODUCCION": "False"}
    assert _leer("SESSION_COOKIE_SECURE", **variables) == "False"


def test_whitenoise_va_justo_despues_de_security_solo_en_produccion():
    assert (
        _leer("MIDDLEWARE[2]", **PRODUCCION) == "'whitenoise.middleware.WhiteNoiseMiddleware'"
    )
    variables = {**PRODUCCION, "DJANGO_PRODUCCION": "False"}
    assert "whitenoise" not in _leer("MIDDLEWARE", **variables)


def test_collectstatic_de_produccion(tmp_path):
    # Con nombres con hash, un estático que referencia un archivo inexistente (p. ej.
    # un .map) hace fallar collectstatic, y con él el arranque en App Service.
    variables = {**PRODUCCION, "DJANGO_STATIC_ROOT": str(tmp_path)}
    resultado = _manage("collectstatic", "--noinput", **variables)
    assert resultado.returncode == 0, resultado.stderr
    manifiesto = (tmp_path / "staticfiles.json").read_text(encoding="utf-8")
    assert "vendor/bootstrap-5.3.8/bootstrap.min.css" in manifiesto
    assert list(tmp_path.glob("css/tivoscanea.*.css.gz"))
