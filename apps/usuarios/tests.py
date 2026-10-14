import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import RequestFactory

from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario, Usuario


@pytest.mark.django_db
class TestUsuarioManager:
    def test_create_user_hashea_la_password_y_usa_email(self, almacen):
        usuario = Usuario.sin_aislamiento.create_user(
            email="nuevo@ficticio.test",
            nombre="Nuevo",
            password="clave123",
            id_almacen=almacen,
        )
        assert usuario.rol == RolUsuario.VENDEDOR
        assert usuario.check_password("clave123")
        assert usuario.password != "clave123"

    def test_create_user_exige_almacen(self, db):
        with pytest.raises(ValueError):
            Usuario.sin_aislamiento.create_user(
                email="x@ficticio.test", nombre="X", password="x"
            )

    def test_create_user_exige_email(self, almacen):
        with pytest.raises(ValueError):
            Usuario.sin_aislamiento.create_user(
                email="", nombre="X", password="x", id_almacen=almacen
            )

    def test_create_superuser_acepta_id_de_almacen(self, almacen):
        admin = Usuario.sin_aislamiento.create_superuser(
            email="super@ficticio.test", nombre="Super", password="x", id_almacen=almacen.pk
        )
        assert admin.is_superuser and admin.is_staff and admin.es_admin
        assert admin.id_almacen == almacen

    def test_email_unico_entre_almacenes(self, datos_a, datos_b):
        with pytest.raises(IntegrityError):
            Usuario.sin_aislamiento.create_user(
                email=datos_a.vendedor.email,
                nombre="Duplicado",
                password="x",
                id_almacen=datos_b.almacen,
            )

    def test_rol_invalido_es_rechazado_por_la_bd(self, almacen):
        with pytest.raises(IntegrityError):
            Usuario.sin_aislamiento.create_user(
                email="r@ficticio.test",
                nombre="R",
                password="x",
                rol="otro",
                id_almacen=almacen,
            )


@pytest.mark.django_db
class TestRolRequerido:
    def _vista(self, request):
        return HttpResponse("ok")

    def test_permite_rol_correcto(self, datos_a):
        request = RequestFactory().get("/")
        request.user = datos_a.admin
        assert rol_requerido(RolUsuario.ADMIN)(self._vista)(request).status_code == 200

    def test_bloquea_rol_incorrecto(self, datos_a):
        request = RequestFactory().get("/")
        request.user = datos_a.vendedor
        with pytest.raises(PermissionDenied):
            rol_requerido(RolUsuario.ADMIN)(self._vista)(request)


@pytest.mark.django_db
class TestPaginasConSesion:
    def test_layout_con_sesion_iniciada_no_rompe(self, client, datos_a):
        # base.html no debe enlazar a URLs que no existen (regresión del 1.3.2).
        client.force_login(datos_a.vendedor)
        assert client.get("/cuentas/login/").status_code == 200

    def test_admin_lista_las_nueve_tablas_sin_errores(self, client, datos_a):
        datos_a.admin.is_staff = datos_a.admin.is_superuser = True
        datos_a.admin.save()
        client.force_login(datos_a.admin)
        for ruta in [
            "almacenes/almacen",
            "usuarios/usuario",
            "inventario/categoria",
            "inventario/producto",
            "inventario/movimientostock",
            "ventas/venta",
            "reporteria/accesoreporte",
        ]:
            assert client.get(f"/admin/{ruta}/").status_code == 200, ruta
