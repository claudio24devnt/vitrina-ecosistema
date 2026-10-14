from rest_framework.permissions import BasePermission

from .models import RolUsuario


class EsAdministrador(BasePermission):
    message = "Sólo el administrador del almacén puede hacer esto."

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.rol == RolUsuario.ADMIN)
