import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory

from apps.usuarios.decorators import rol_requerido
from apps.usuarios.models import RolUsuario, Usuario


@pytest.mark.django_db
class TestUsuarioManager:
    def test_create_user_usa_email_como_username(self):
        usuario = Usuario.objects.create_user(
            email="vendedor@tivoscanea.cl", nombre="Vendedor Uno", password="clave123"
        )
        assert usuario.email == "vendedor@tivoscanea.cl"
        assert usuario.rol == RolUsuario.VENDEDOR
        assert usuario.check_password("clave123")
        assert usuario.password != "clave123"

    def test_create_superuser_asigna_rol_admin_y_permisos(self):
        admin = Usuario.objects.create_superuser(
            email="admin@tivoscanea.cl", nombre="Admin", password="clave123"
        )
        assert admin.rol == RolUsuario.ADMIN
        assert admin.is_staff is True
        assert admin.is_superuser is True
        assert admin.es_admin is True

    def test_create_user_sin_email_lanza_error(self):
        with pytest.raises(ValueError):
            Usuario.objects.create_user(email="", nombre="Sin email", password="x")


@pytest.mark.django_db
class TestRolRequerido:
    def _vista_solo_admin(self, request):
        return HttpResponse("ok")

    def test_permite_acceso_con_rol_correcto(self):
        admin = Usuario.objects.create_user(
            email="admin@tivoscanea.cl",
            nombre="Admin",
            password="x",
            rol=RolUsuario.ADMIN,
        )
        vista = rol_requerido(RolUsuario.ADMIN)(self._vista_solo_admin)
        request = RequestFactory().get("/")
        request.user = admin

        respuesta = vista(request)
        assert respuesta.status_code == 200

    def test_bloquea_acceso_con_rol_incorrecto(self):
        vendedor = Usuario.objects.create_user(
            email="vendedor@tivoscanea.cl",
            nombre="Vendedor",
            password="x",
            rol=RolUsuario.VENDEDOR,
        )
        vista = rol_requerido(RolUsuario.ADMIN)(self._vista_solo_admin)
        request = RequestFactory().get("/")
        request.user = vendedor

        with pytest.raises(PermissionDenied):
            vista(request)
