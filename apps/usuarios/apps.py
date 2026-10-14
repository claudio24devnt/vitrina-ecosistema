from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.usuarios"

    def ready(self):
        # Registra los checks de despliegue del proyecto (ver tivoscanea/checks.py).
        from tivoscanea import checks  # noqa: F401
