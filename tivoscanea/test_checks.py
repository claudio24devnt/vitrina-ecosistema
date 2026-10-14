import pytest
from django.core.checks import run_checks

from tivoscanea.checks import CLAVE_CI


def _errores_secret_key(include_deployment_checks):
    return [
        error
        for error in run_checks(include_deployment_checks=include_deployment_checks)
        if error.id == "tivoscanea.E001"
    ]


@pytest.mark.parametrize("clave", [CLAVE_CI, "prefijo-ci-only-sufijo"])
def test_check_deploy_rechaza_la_clave_del_ci(settings, clave):
    settings.SECRET_KEY = clave
    assert len(_errores_secret_key(include_deployment_checks=True)) == 1


def test_check_deploy_acepta_una_clave_real(settings):
    settings.SECRET_KEY = "x7$k2!q9-una-clave-larga-generada-para-produccion-0f3a"
    assert _errores_secret_key(include_deployment_checks=True) == []


def test_check_no_corre_fuera_de_deploy(settings):
    settings.SECRET_KEY = CLAVE_CI
    assert _errores_secret_key(include_deployment_checks=False) == []
