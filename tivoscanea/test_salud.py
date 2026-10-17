"""El sondeo de salud de App Service llega con la IP interna del contenedor como host."""

import pytest


def test_salud_responde_con_cualquier_host(client):
    respuesta = client.get("/salud/", HTTP_HOST="169.254.129.6:8000")
    assert respuesta.status_code == 200
    assert respuesta.content == b"ok"


@pytest.mark.django_db
def test_salud_no_exige_sesion_ni_toca_la_base(client, django_assert_num_queries):
    with django_assert_num_queries(0):
        assert client.get("/salud/").status_code == 200


@pytest.mark.django_db
def test_el_resto_sigue_validando_el_host(client, settings):
    settings.ALLOWED_HOSTS = ["app.ficticio.test"]
    assert client.get("/cuentas/login/", HTTP_HOST="169.254.129.6:8000").status_code == 400
    assert client.get("/cuentas/login/", HTTP_HOST="app.ficticio.test").status_code == 200
