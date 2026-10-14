"""Gestión de usuarios del almacén (CU-06)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.almacenes.errores import ReglaDeNegocioError

from .models import RolUsuario, Usuario


def crear_vendedor(*, almacen, nombre, email, password):
    """
    Crea un usuario con rol vendedor (registra ventas y consulta stock).
    El correo es único en todo TivoScanea, no sólo en el almacén: con él se inicia sesión.
    """
    nombre = (nombre or "").strip()
    email = Usuario.sin_aislamiento.normalize_email((email or "").strip()).lower()
    if not nombre:
        raise ReglaDeNegocioError("Escribe el nombre del vendedor.")

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
                rol=RolUsuario.VENDEDOR,
                id_almacen=almacen,
            )
    except IntegrityError:
        raise ReglaDeNegocioError("Ese correo ya está registrado. Usa otro correo.") from None


def vendedores_del_almacen(almacen):
    return Usuario.objects.del_almacen(almacen).filter(rol=RolUsuario.VENDEDOR)
