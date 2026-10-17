"""
Configuracion de Django para TivoScanea.

Todos los valores sensibles o dependientes del entorno se leen desde
variables de entorno (ver .env.example). Nunca hardcodear secretos aqui.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# Orígenes HTTPS aceptados en los POST (host de Azure y dominio propio).
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Producción (App Service en Azure). Es una bandera aparte de
# DEBUG porque el CI corre con DEBUG=False sobre HTTP y no debe exigir HTTPS.
PRODUCCION = env.bool("DJANGO_PRODUCCION", default=False)


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.almacenes",
    "apps.usuarios",
    "apps.inventario",
    "apps.ventas",
    "apps.reporteria",
]

MIDDLEWARE = [
    # Primero: responde el sondeo de salud de App Service sin validar el host.
    "tivoscanea.salud.SaludMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.almacenes.middleware.AlmacenActualMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tivoscanea.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "tivoscanea.wsgi.application"


# Base de datos: PostgreSQL 16 (Azure Database for PostgreSQL Flexible Server en produccion)
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="tivoscanea_db"),
        "USER": env("DB_USER", default="tivoscanea_user"),
        "PASSWORD": env("DB_PASSWORD", default=""),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
        # Conexiones reutilizadas entre solicitudes: ahorra el saludo TLS con Azure.
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=0),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": env("DB_SSLMODE", default="prefer")},
    }
}


# Usuario personalizado (ver apps.usuarios.models.Usuario)
AUTH_USER_MODEL = "usuarios.Usuario"

LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "usuarios:login"


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internacionalizacion: almacen de barrio en Chile
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "es-cl"

TIME_ZONE = "America/Santiago"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = env.path("DJANGO_STATIC_ROOT", default=BASE_DIR / "staticfiles")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # En producción, nombres con hash (caché larga) y comprimidos; en desarrollo y
    # pruebas, el almacenamiento simple, que no exige correr collectstatic antes.
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if PRODUCCION
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# API REST: sesión de Django, sólo usuarios autenticados, respuestas JSON.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}


# Reglas de negocio configurables (ver Informe 2)

UMBRAL_CAIDA_VENTAS_PORCENTAJE = env.int("UMBRAL_CAIDA_VENTAS_PORCENTAJE", default=20)


# En producción la propia aplicación sirve los estáticos (App Service no tiene un
# servidor web aparte); en desarrollo lo hace runserver.
if PRODUCCION:
    MIDDLEWARE.insert(
        MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
        "whitenoise.middleware.WhiteNoiseMiddleware",
    )

# Seguridad en producción (OWASP Top 10, §8). El TLS lo termina App Service, que
# reenvía X-Forwarded-Proto: https.
if PRODUCCION:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # La redirección a HTTPS la hace App Service (httpsOnly). Hacerla también aquí
    # convertiría en 301 el chequeo de salud interno, que llega por HTTP.
    SILENCED_SYSTEM_CHECKS = ["security.W008"]

# Registro a la salida estándar: App Service la guarda en su log stream.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["consola"], "level": "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["consola"], "level": "ERROR", "propagate": False},
    },
}
