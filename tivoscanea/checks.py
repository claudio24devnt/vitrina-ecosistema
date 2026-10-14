"""
Checks de despliegue propios del proyecto.

Django ejecuta los checks con etiqueta `deploy` sólo con
`python manage.py check --deploy`, no al arrancar el servidor. Por eso el
pipeline de despliegue (paquete 1.6) debe correr ese comando con
`--fail-level ERROR` antes de publicar: ahí es donde este check bloquea.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

CLAVE_CI = "ci-only-not-a-secret-do-not-reuse"


@register(Tags.security, deploy=True)
def secret_key_no_es_la_de_ci(app_configs, **kwargs):
    clave = getattr(settings, "SECRET_KEY", "") or ""
    if clave == CLAVE_CI or "ci-only" in clave:
        return [
            Error(
                "SECRET_KEY es la clave ficticia del CI.",
                hint="En producción la clave se lee de Azure Key Vault con identidad "
                "administrada; nunca se reutiliza la del CI.",
                id="tivoscanea.E001",
            )
        ]
    return []
