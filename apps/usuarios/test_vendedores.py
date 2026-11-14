"""CU-06: gestión de vendedores (servicio y pantalla)."""

import pytest
from django.urls import reverse

from apps.almacenes.errores import ReglaDeNegocioError
from apps.usuarios.models import RolUsuario, Usuario
from apps.usuarios.servicios import (
    cambiar_estado_vendedor,
    crear_vendedor,
    eliminar_vendedor,
    vendedor_tiene_historial,
)

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


# ---- Eliminar, desactivar y reactivar (CU-06) ----------------------------------------


@pytest.fixture
def vendedor_nuevo(datos_a):
    """Vendedor sin ventas ni movimientos: se puede eliminar."""
    return crear_vendedor(
        almacen=datos_a.almacen,
        nombre="Vendedor Ficticio Nuevo",
        email="nuevo@ficticio.test",
        password=CLAVE_VALIDA,
    )


@pytest.mark.django_db
class TestEliminarVendedor:
    def test_sin_historial_se_elimina(self, datos_a, vendedor_nuevo):
        assert not vendedor_tiene_historial(vendedor_nuevo)
        eliminar_vendedor(autor=datos_a.admin, vendedor=vendedor_nuevo)
        assert not Usuario.sin_aislamiento.filter(pk=vendedor_nuevo.pk).exists()

    def test_con_ventas_no_se_elimina(self, datos_a):
        assert vendedor_tiene_historial(datos_a.vendedor)
        with pytest.raises(ReglaDeNegocioError, match="Desactiva su cuenta"):
            eliminar_vendedor(autor=datos_a.admin, vendedor=datos_a.vendedor)
        assert Usuario.sin_aislamiento.filter(pk=datos_a.vendedor.pk).exists()

    def test_solo_el_administrador_de_su_almacen(self, datos_a, datos_b, vendedor_nuevo):
        for autor in (datos_b.admin, datos_a.vendedor):
            with pytest.raises(ReglaDeNegocioError, match="No puedes"):
                eliminar_vendedor(autor=autor, vendedor=vendedor_nuevo)
        with pytest.raises(ReglaDeNegocioError):
            eliminar_vendedor(autor=datos_a.admin, vendedor=datos_a.admin)
        assert Usuario.sin_aislamiento.filter(pk=vendedor_nuevo.pk).exists()

    def test_desactivar_y_reactivar(self, datos_a):
        cambiar_estado_vendedor(autor=datos_a.admin, vendedor=datos_a.vendedor, activo=False)
        assert not Usuario.sin_aislamiento.get(pk=datos_a.vendedor.pk).is_active
        cambiar_estado_vendedor(autor=datos_a.admin, vendedor=datos_a.vendedor, activo=True)
        assert Usuario.sin_aislamiento.get(pk=datos_a.vendedor.pk).is_active

    def test_otro_almacen_no_desactiva(self, datos_a, datos_b):
        with pytest.raises(ReglaDeNegocioError):
            cambiar_estado_vendedor(
                autor=datos_b.admin, vendedor=datos_a.vendedor, activo=False
            )


@pytest.mark.django_db
class TestPantallaEliminarVendedor:
    def _url(self, nombre, usuario):
        return reverse(f"usuarios:{nombre}", args=[usuario.pk])

    def test_confirmacion_y_eliminacion(self, client, datos_a, vendedor_nuevo):
        client.force_login(datos_a.admin)
        url = self._url("eliminar_vendedor", vendedor_nuevo)
        assert url in client.get(reverse("usuarios:vendedores")).content.decode()
        html = client.get(url).content.decode()
        assert "Esto no se puede deshacer." in html
        assert Usuario.sin_aislamiento.filter(pk=vendedor_nuevo.pk).exists()

        respuesta = client.post(url, follow=True)
        assert (
            "Se eliminó la cuenta de «Vendedor Ficticio Nuevo»." in respuesta.content.decode()
        )
        assert not Usuario.sin_aislamiento.filter(pk=vendedor_nuevo.pk).exists()

    def test_con_historial_ofrece_desactivar(self, client, datos_a):
        client.force_login(datos_a.admin)
        url = self._url("eliminar_vendedor", datos_a.vendedor)
        html = client.get(url).content.decode()
        assert "No se puede eliminar" in html
        assert self._url("estado_vendedor", datos_a.vendedor) in html

        respuesta = client.post(url, follow=True)
        assert "no se puede eliminar" in respuesta.content.decode()
        assert Usuario.sin_aislamiento.filter(pk=datos_a.vendedor.pk).exists()

    def test_desactivado_no_ingresa_y_pierde_la_sesion(self, client, datos_a):
        from django.test import Client

        caja = Client()
        caja.force_login(datos_a.vendedor)
        assert caja.get(reverse("inicio")).status_code == 200

        client.force_login(datos_a.admin)
        url = self._url("estado_vendedor", datos_a.vendedor)
        html = client.post(url, {"activo": "0"}, follow=True).content.decode()
        assert "quedó desactivada" in html
        assert "Cuenta desactivada" in html

        assert caja.get(reverse("inicio")).status_code == 302
        entrada = Client().post(
            reverse("usuarios:login"),
            {"username": datos_a.vendedor.email, "password": "clave-de-prueba"},
        )
        assert entrada.status_code == 200  # vuelve al formulario: no ingresó

        client.post(url, {"activo": "1"})
        entrada = Client().post(
            reverse("usuarios:login"),
            {"username": datos_a.vendedor.email, "password": "clave-de-prueba"},
        )
        assert entrada.status_code == 302

    def test_otro_almacen_y_vendedores_no_entran(
        self, client, datos_a, datos_b, vendedor_nuevo
    ):
        client.force_login(datos_b.admin)
        assert client.get(self._url("eliminar_vendedor", vendedor_nuevo)).status_code == 404
        assert client.post(self._url("eliminar_vendedor", vendedor_nuevo)).status_code == 404
        estado = self._url("estado_vendedor", datos_a.vendedor)
        assert client.post(estado, {"activo": "0"}).status_code == 404

        client.force_login(datos_a.vendedor)
        assert client.post(self._url("eliminar_vendedor", vendedor_nuevo)).status_code == 403
        assert Usuario.sin_aislamiento.filter(pk=vendedor_nuevo.pk).exists()
        assert Usuario.sin_aislamiento.get(pk=datos_a.vendedor.pk).is_active

    def test_estado_solo_por_post(self, client, datos_a):
        client.force_login(datos_a.admin)
        assert client.get(self._url("estado_vendedor", datos_a.vendedor)).status_code == 405
