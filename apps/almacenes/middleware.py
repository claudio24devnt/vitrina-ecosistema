from django.utils.functional import SimpleLazyObject


def _almacen_del_usuario(request):
    usuario = request.user
    if not usuario.is_authenticated:
        return None
    return usuario.id_almacen


class AlmacenActualMiddleware:
    """
    Expone `request.almacen`: el almacén del usuario con sesión iniciada (o None).
    Las vistas filtran todo con `Modelo.objects.del_almacen(request.almacen)`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.almacen = SimpleLazyObject(lambda: _almacen_del_usuario(request))
        return self.get_response(request)
