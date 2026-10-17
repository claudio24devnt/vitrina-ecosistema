from django.http import HttpResponse

RUTA_SALUD = "/salud/"


class SaludMiddleware:
    """
    Responde /salud/ antes que cualquier otro middleware. App Service sondea la app
    con la IP interna del contenedor como host (p. ej. 169.254.129.6:8000), que
    cambia y no puede ir en ALLOWED_HOSTS: sin esto Django responde 400
    (DisallowedHost) y la plataforma puede dar la instancia por enferma.

    Sólo dice que el proceso atiende; no consulta la base, para que un corte de
    PostgreSQL no haga que App Service reinicie la app en bucle.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == RUTA_SALUD:
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
