"""
Alta de almacenes por el operador de la plataforma: RUT, servicio transaccional,
comando crear_operador y pantalla /plataforma/almacenes/. Datos FICTICIOS: los RUT
son inventados (con dígito verificador válido) y no corresponden a almacenes reales.
"""

from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import Almacen, FranjaHoraria
from apps.almacenes.servicios import (
    PLAN_OPERACION,
    alta_almacen,
    almacenes_clientes,
    normalizar_rut,
)
from apps.usuarios.models import RolUsuario, Usuario

CLAVE = "Ficticia-2026-segura"
URL = "/plataforma/almacenes/"


def _alta(**cambios):
    datos = {
        "razon_social": "Almacén Ficticio El Roble",
        "rut": "76.000.101-5",
        "plan": "basico",
        "direccion": "Calle Ficticia 456",
        "nombre_admin": "Administradora Ficticia",
        "email_admin": "roble@ficticio.test",
        "password_admin": CLAVE,
    }
    datos.update(cambios)
    return alta_almacen(**datos)


class TestRut:
    @pytest.mark.parametrize(
        "texto, normalizado",
        [
            ("76.000.101-5", "76000101-5"),
            ("76000101-5", "76000101-5"),
            ("760001015", "76000101-5"),
            (" 7.654.321-6 ", "7654321-6"),
            ("11.111.111-1", "11111111-1"),
        ],
    )
    def test_formatos_aceptados(self, texto, normalizado):
        assert normalizar_rut(texto) == normalizado

    def test_dv_k_en_minuscula(self):
        # 10.000.013-K: el resto 10 se escribe K.
        assert normalizar_rut("10.000.013-k") == "10000013-K"

    @pytest.mark.parametrize("texto", ["76.000.101-4", "", "abc", "123-4", "76.000.101"])
    def test_invalidos(self, texto):
        with pytest.raises(ReglaDeNegocioError):
            normalizar_rut(texto)


@pytest.mark.django_db
class TestAltaAlmacen:
    def test_crea_almacen_franjas_y_administrador(self):
        almacen, admin = _alta()
        assert (almacen.rut, almacen.plan) == ("76000101-5", "basico")
        assert FranjaHoraria.objects.del_almacen(almacen).count() == 5
        assert admin.id_almacen == almacen
        assert admin.rol == RolUsuario.ADMIN
        assert not admin.is_superuser and admin.check_password(CLAVE)

    def test_rut_repetido_se_rechaza(self):
        _alta()
        with pytest.raises(ReglaDeNegocioError, match="Almacén Ficticio El Roble"):
            _alta(rut="76000101-5", email_admin="otro@ficticio.test")

    def test_si_falla_el_administrador_no_queda_el_almacen(self, datos_a):
        with pytest.raises(ReglaDeNegocioError, match="correo ya está registrado"):
            _alta(email_admin=datos_a.admin.email)
        assert not Almacen.sin_aislamiento.filter(rut="76000101-5").exists()
        assert not FranjaHoraria.sin_aislamiento.filter(id_almacen__rut="76000101-5").exists()

    def test_contrasena_debil_no_deja_nada(self):
        with pytest.raises(ReglaDeNegocioError):
            _alta(password_admin="123")
        assert not Almacen.sin_aislamiento.filter(rut="76000101-5").exists()

    @pytest.mark.parametrize("plan", ["", PLAN_OPERACION])
    def test_plan_obligatorio_y_no_de_operacion(self, plan):
        with pytest.raises(ReglaDeNegocioError, match="plan"):
            _alta(plan=plan)

    def test_la_lista_excluye_el_almacen_de_operacion(self, operador):
        cliente, _ = _alta()
        assert list(almacenes_clientes()) == [cliente]


@pytest.fixture
def operador(db):
    with mock.patch("getpass.getpass", return_value=CLAVE):
        call_command(
            "crear_operador",
            "--nombre",
            "Operador Ficticio",
            "--email",
            "operador@ficticio.test",
            "--rut",
            "76.000.102-3",
            stdout=mock.MagicMock(),
        )
    return Usuario.sin_aislamiento.get(email="operador@ficticio.test")


@pytest.mark.django_db
class TestCrearOperador:
    def test_crea_superusuario_en_almacen_de_operacion(self, operador):
        assert operador.is_superuser and operador.is_staff
        assert operador.id_almacen.plan == PLAN_OPERACION
        assert operador.check_password(CLAVE)

    def test_un_segundo_operador_reutiliza_el_almacen(self, operador):
        with mock.patch("getpass.getpass", return_value=CLAVE):
            call_command(
                "crear_operador",
                "--nombre",
                "Otro Operador",
                "--email",
                "otro.operador@ficticio.test",
                "--rut",
                "76.000.103-1",
                stdout=mock.MagicMock(),
            )
        assert Almacen.sin_aislamiento.filter(plan=PLAN_OPERACION).count() == 1

    def test_claves_distintas(self, db):
        with mock.patch("getpass.getpass", side_effect=[CLAVE, "otra"]):
            with pytest.raises(CommandError, match="no coinciden"):
                call_command(
                    "crear_operador", "--nombre", "X", "--email", "x@ficticio.test",
                    "--rut", "76.000.102-3",
                )  # fmt: skip
        assert not Almacen.sin_aislamiento.filter(plan=PLAN_OPERACION).exists()

    def test_rut_invalido(self, db):
        with pytest.raises(CommandError, match="dígito verificador"):
            call_command(
                "crear_operador", "--nombre", "X", "--email", "x@ficticio.test",
                "--rut", "76.000.102-4",
            )  # fmt: skip


@pytest.mark.django_db
class TestPantallaPlataforma:
    def _datos(self, **cambios):
        datos = {
            "razon_social": "Almacén Ficticio La Palma",
            "rut": "76.000.103-1",
            "direccion": "",
            "plan": "basico",
            "nombre_admin": "Admin Ficticio Palma",
            "email_admin": "palma@ficticio.test",
            "password": CLAVE,
            "password_repetida": CLAVE,
        }
        datos.update(cambios)
        return datos

    def test_operador_da_de_alta_y_el_administrador_entra(self, client, operador):
        client.force_login(operador)
        respuesta = client.post(URL, self._datos(), follow=True)
        assert "Almacén «Almacén Ficticio La Palma» creado" in respuesta.content.decode()
        assert "76000103-1" in respuesta.content.decode()

        client.logout()
        entrada = client.post(
            reverse("usuarios:login"), {"username": "palma@ficticio.test", "password": CLAVE}
        )
        assert entrada.status_code == 302

    def test_errores_se_muestran_en_el_formulario(self, client, operador):
        client.force_login(operador)
        respuesta = client.post(URL, self._datos(rut="76.000.103-2", password_repetida="x"))
        html = respuesta.content.decode()
        assert "Las contraseñas no coinciden." in html
        client.post(URL, self._datos(password_repetida=CLAVE))
        assert not Almacen.sin_aislamiento.filter(rut="76000103-2").exists()

    @pytest.mark.parametrize("rol", ["admin", "vendedor"])
    def test_usuarios_de_un_almacen_no_entran(self, client, datos_a, rol):
        client.force_login(getattr(datos_a, rol))
        assert client.get(URL).status_code == 403
        assert client.post(URL, self._datos()).status_code == 403
        assert not Almacen.sin_aislamiento.filter(rut="76000103-1").exists()

    def test_el_menu_muestra_almacenes_solo_al_operador(self, client, operador, datos_a):
        client.force_login(operador)
        assert URL in client.get(reverse("inicio")).content.decode()
        client.force_login(datos_a.admin)
        assert URL not in client.get(reverse("inicio")).content.decode()

    def test_sin_sesion_va_al_login(self, client):
        assert client.get(URL).status_code == 302
