"""
Gestión de usuarios del almacén (CU-06), del administrador inicial de cada almacén y
de las contraseñas: restablecerlas sin correo (el administrador a sus vendedores, el
operador a los administradores) y limitar los correos de recuperación.
"""

import hashlib
import logging

from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.almacenes.errores import ReglaDeNegocioError

from .models import RolUsuario, Usuario


def _crear_usuario(*, almacen, nombre, email, password, rol, quien, **extra):
    """
    Reglas comunes al crear cualquier usuario: nombre obligatorio, correo único en
    todo TivoScanea (no sólo en el almacén: con él se inicia sesión) y contraseña
    que pase los validadores de Django. `quien` nombra al usuario en los mensajes.
    """
    nombre = (nombre or "").strip()
    email = Usuario.sin_aislamiento.normalize_email((email or "").strip()).lower()
    if not nombre:
        raise ReglaDeNegocioError(f"Escribe el nombre del {quien}.")

    # Consulta transversal intencional: el correo es único entre todos los almacenes.
    if Usuario.sin_aislamiento.filter(email__iexact=email).exists():
        raise ReglaDeNegocioError("Ese correo ya está registrado. Usa otro correo.")

    candidato = Usuario(email=email, nombre=nombre, id_almacen=almacen)
    try:
        validate_password(password, user=candidato)
    except ValidationError as error:
        raise ReglaDeNegocioError(" ".join(error.messages)) from None

    try:
        with transaction.atomic():
            return Usuario.sin_aislamiento.create_user(
                email=email,
                nombre=nombre,
                password=password,
                rol=rol,
                id_almacen=almacen,
                **extra,
            )
    except IntegrityError:
        raise ReglaDeNegocioError("Ese correo ya está registrado. Usa otro correo.") from None


def crear_vendedor(*, almacen, nombre, email, password):
    """Crea un usuario con rol vendedor (registra ventas y consulta stock)."""
    return _crear_usuario(
        almacen=almacen,
        nombre=nombre,
        email=email,
        password=password,
        rol=RolUsuario.VENDEDOR,
        quien="vendedor",
    )


def crear_administrador(*, almacen, nombre, email, password, operador=False):
    """
    Administrador de un almacén. Con `operador`, además es el operador de la
    plataforma (is_superuser): da de alta almacenes y entra al admin de Django.
    """
    return _crear_usuario(
        almacen=almacen,
        nombre=nombre,
        email=email,
        password=password,
        rol=RolUsuario.ADMIN,
        quien="administrador",
        is_superuser=operador,
        is_staff=operador,
    )


def vendedores_del_almacen(almacen):
    return Usuario.objects.del_almacen(almacen).filter(rol=RolUsuario.VENDEDOR)


# ---- Contraseñas ----------------------------------------------------------------

registro_seguridad = logging.getLogger("tivoscanea.seguridad")


def _validar_contrasena(password, usuario):
    try:
        validate_password(password, user=usuario)
    except ValidationError as error:
        raise ReglaDeNegocioError(" ".join(error.messages)) from None


def puede_restablecer(autor, usuario):
    """
    Quién puede asignar una contraseña nueva a otro, sin conocer la anterior:
    - el administrador, a los vendedores de su almacén;
    - el operador de la plataforma, a los administradores de los almacenes clientes.
    Nadie a sí mismo: para eso está el cambio con la contraseña actual.
    """
    if autor.pk == usuario.pk or not usuario.is_active:
        return False
    if autor.is_superuser:
        return usuario.rol == RolUsuario.ADMIN and not usuario.is_superuser
    return (
        autor.es_admin
        and usuario.rol == RolUsuario.VENDEDOR
        and usuario.id_almacen_id == autor.id_almacen_id
    )


def restablecer_contrasena(*, autor, usuario, password):
    """
    Asigna una contraseña nueva a `usuario` (ver `puede_restablecer`). Las sesiones
    que tenga abiertas se cierran solas: Django las firma con el hash de la contraseña.
    Queda en el registro quién la cambió (log de App Service), sin la contraseña.
    """
    if not puede_restablecer(autor, usuario):
        raise ReglaDeNegocioError("No puedes cambiar la contraseña de ese usuario.")
    _validar_contrasena(password, usuario)
    usuario.set_password(password)
    usuario.save(update_fields=["password"])
    registro_seguridad.info(
        "Contraseña restablecida: usuario %s (almacén %s) por usuario %s",
        usuario.pk,
        usuario.id_almacen_id,
        autor.pk,
    )
    return usuario


def administradores_de_clientes():
    """
    Administradores de los almacenes clientes, para la pantalla del operador.
    Consulta transversal intencional (como `almacenes_clientes`): no incluye al
    operador ni toca datos de ventas.
    """
    return (
        Usuario.sin_aislamiento.filter(rol=RolUsuario.ADMIN, is_superuser=False)
        .select_related("id_almacen")
        .order_by("id_almacen__razon_social", "nombre")
    )


# Correos de recuperación por dirección y hora. Evita que alguien use el formulario
# para llenarle la bandeja a otro. El contador vive en la caché de cada proceso de
# gunicorn (sin Redis, §2.1): con 2 workers el tope real es el doble.
MAX_CORREOS_RECUPERACION_POR_HORA = 3


def admitir_correo_de_recuperacion(email):
    """True si todavía se puede enviar un correo de recuperación a `email` esta hora."""
    huella = hashlib.sha256((email or "").strip().lower().encode()).hexdigest()
    clave = f"recuperacion:{huella}"
    cache.add(clave, 0, timeout=60 * 60)
    try:
        enviados = cache.incr(clave)
    except ValueError:  # venció justo entre add e incr
        cache.set(clave, 1, timeout=60 * 60)
        enviados = 1
    return enviados <= MAX_CORREOS_RECUPERACION_POR_HORA
