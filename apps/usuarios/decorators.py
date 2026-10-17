from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def rol_requerido(*roles):
    """
    Decorador para vistas basadas en funcion: exige login y que
    request.user.rol este entre los roles permitidos.
    """

    def decorador(view_func):
        @wraps(view_func)
        @login_required
        def _envuelta(request, *args, **kwargs):
            if request.user.rol not in roles:
                raise PermissionDenied("No tienes permiso para entrar a esta sección.")
            return view_func(request, *args, **kwargs)

        return _envuelta

    return decorador


def operador_requerido(view_func):
    """Sólo el operador de la plataforma (is_superuser): da de alta almacenes."""

    @wraps(view_func)
    @login_required
    def _envuelta(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Esta sección es sólo para el operador de TivoScanea.")
        return view_func(request, *args, **kwargs)

    return _envuelta
