"""Gestión de usuarios del almacén (CU-06) y del administrador inicial de cada almacén."""

from django.contrib.auth.password_validation import validate_password
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
