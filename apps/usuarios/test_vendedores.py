"""CU-06: gestión de vendedores (servicio y pantalla)."""

import pytest
from django.urls import reverse

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.models import RolUsuario, Usuario
from apps.usuarios.servicios import crear_vendedor

CLAVE_VALIDA = "mesón-2026-segura"


@pytest.mark.django_db
class TestCrearVendedor:
    def test_crea_vendedor_con_password_hasheada(self, almacen):
        vendedor = crear_vendedor(
            almacen=almacen,
            nombre="Vendedora Ficticia",
            email="Nueva@Ficticio.Test",
            password=CLAVE_VALIDA,
        )
        assert vendedor.rol == RolUsuario.VENDEDOR
        assert vendedor.email == "nueva@ficticio.test"
        assert vendedor.id_almacen == almacen
        assert vendedor.check_password(CLAVE_VALIDA)
        assert vendedor.password != CLAVE_VALIDA

    def test_correo_ya_registrado_es_rechazado(self, datos_a):
        with pytest.raises(ReglaDeNegocioError, match="Ese correo ya está registrado"):
            crear_vendedor(
                almacen=datos_a.almacen,
                nombre="Otro",
                email=datos_a.vendedor.email.upper(),
                password=CLAVE_VALIDA,
            )

    def test_correo_de_otro_almacen_tambien_es_rechazado(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            crear_vendedor(
                almacen=datos_b.almacen,
                nombre="Otro",
                email=datos_a.vendedor.email,
                password=CLAVE_VALIDA,
            )

    @pytest.mark.parametrize("clave", ["123", "password", "12345678"])
    def test_contrasena_debil_es_rechazada(self, almacen, clave):
        with pytest.raises(ReglaDeNegocioError):
            crear_vendedor(
                almacen=almacen, nombre="X", email="x@ficticio.test", password=clave
            )
        assert not Usuario.sin_aislamiento.filter(email="x@ficticio.test").exists()

    def test_nombre_vacio_es_rechazado(self, almacen):
        with pytest.raises(ReglaDeNegocioError):
            crear_vendedor(
                almacen=almacen, nombre="  ", email="y@ficticio.test", password=CLAVE_VALIDA
            )


@pytest.mark.django_db
class TestPantallaVendedores:
    def _post(self, client, **cambios):
        datos = {
            "nombre": "Vendedor Nuevo",
            "email": "nuevo.vendedor@ficticio.test",
            "password": CLAVE_VALIDA,
            "password_repetida": CLAVE_VALIDA,
        }
        datos.update(cambios)
        return client.post(reverse("usuarios:vendedores"), datos)

    def test_admin_crea_vendedor_en_su_almacen(self, client, datos_a):
        client.force_login(datos_a.admin)
        assert self._post(client).status_code == 302
        nuevo = Usuario.sin_aislamiento.get(email="nuevo.vendedor@ficticio.test")
        assert nuevo.id_almacen == datos_a.almacen
        assert nuevo.rol == RolUsuario.VENDEDOR

    def test_el_nuevo_vendedor_puede_iniciar_sesion(self, client, datos_a):
        client.force_login(datos_a.admin)
        self._post(client)
        client.logout()
        assert client.login(email="nuevo.vendedor@ficticio.test", password=CLAVE_VALIDA)

    def test_contrasenas_distintas(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = self._post(client, password_repetida="otra-cosa-2026")
        assert "Las contraseñas no coinciden" in respuesta.content.decode()

    def test_correo_repetido_se_informa(self, client, datos_a):
        client.force_login(datos_a.admin)
        respuesta = self._post(client, email=datos_a.vendedor.email)
        assert "Ese correo ya está registrado" in respuesta.content.decode()

    def test_lista_solo_vendedores_del_almacen(self, client, datos_a, datos_b):
        client.force_login(datos_a.admin)
        contenido = client.get(reverse("usuarios:vendedores")).content.decode()
        assert datos_a.vendedor.email in contenido
        assert datos_b.vendedor.email not in contenido
