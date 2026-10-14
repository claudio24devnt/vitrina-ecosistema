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
