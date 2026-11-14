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
from django.db.models import ProtectedError

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
    """Vendedores del almacén: primero los activos, luego los desactivados."""
    return (
        Usuario.objects.del_almacen(almacen)
        .filter(rol=RolUsuario.VENDEDOR)
        .order_by("-is_active", "nombre")
    )


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
    limpiar_ingresos_fallidos(usuario.email)
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


def _huella(email):
    """El correo no se guarda tal cual en la caché ni en el log."""
    return hashlib.sha256((email or "").strip().lower().encode()).hexdigest()


def _sumar(clave, ventana_segundos):
    """Suma 1 al contador `clave`, que se borra solo al pasar la ventana."""
    cache.add(clave, 0, timeout=ventana_segundos)
    try:
        return cache.incr(clave)
    except ValueError:  # venció justo entre add e incr
        cache.set(clave, 1, timeout=ventana_segundos)
        return 1


def admitir_correo_de_recuperacion(email):
    """True si todavía se puede enviar un correo de recuperación a `email` esta hora."""
    enviados = _sumar(f"recuperacion:{_huella(email)}", 60 * 60)
    return enviados <= MAX_CORREOS_RECUPERACION_POR_HORA


# Intentos de ingreso fallidos (OWASP A07: fuerza bruta). Por correo, para proteger
# una cuenta; por IP, para frenar a quien prueba muchas cuentas. Mientras dura el
# bloqueo no se calcula el hash: también evita gastar ~3 s de CPU del B1 por intento.
# Misma limitación que los correos: caché por proceso de gunicorn.
MAX_INGRESOS_FALLIDOS_POR_CORREO = 5
MAX_INGRESOS_FALLIDOS_POR_IP = 20
VENTANA_INGRESOS_SEGUNDOS = 15 * 60


def ip_del_cliente(request):
    """
    IP del cliente detrás del frontal de App Service, que la agrega al final de
    X-Forwarded-For como «ip:puerto». Se toma la última: las anteriores las puede
    inventar el cliente.
    """
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = reenviada.split(",")[-1].strip() if reenviada else request.META.get("REMOTE_ADDR", "")
    if ip.startswith("["):  # IPv6 con puerto: [::1]:1234
        return ip[1:].split("]")[0]
    if ip.count(":") == 1:  # IPv4 con puerto
        return ip.split(":")[0]
    return ip


def _claves_de_ingreso(email, ip):
    return f"ingreso:correo:{_huella(email)}", f"ingreso:ip:{ip}"


def ingreso_bloqueado(email, ip):
    por_correo, por_ip = _claves_de_ingreso(email, ip)
    return (cache.get(por_correo, 0) >= MAX_INGRESOS_FALLIDOS_POR_CORREO) or (
        cache.get(por_ip, 0) >= MAX_INGRESOS_FALLIDOS_POR_IP
    )


def registrar_ingreso_fallido(email, ip):
    por_correo, por_ip = _claves_de_ingreso(email, ip)
    fallidos_correo = _sumar(por_correo, VENTANA_INGRESOS_SEGUNDOS)
    fallidos_ip = _sumar(por_ip, VENTANA_INGRESOS_SEGUNDOS)
    if (
        fallidos_correo == MAX_INGRESOS_FALLIDOS_POR_CORREO
        or fallidos_ip == MAX_INGRESOS_FALLIDOS_POR_IP
    ):
        registro_seguridad.warning(
            "Ingreso bloqueado %s min: correo %s, IP %s",
            VENTANA_INGRESOS_SEGUNDOS // 60,
            _huella(email)[:12],
            ip,
        )


def limpiar_ingresos_fallidos(email):
    """Tras ingresar bien o cambiar la contraseña, la cuenta parte de cero."""
    por_correo, _ = _claves_de_ingreso(email, "")
    cache.delete(por_correo)


# ---- Eliminar y desactivar vendedores (CU-06) --------------------------------------


def _verificar_gestion_de_vendedor(autor, vendedor):
    """Sólo el administrador del mismo almacén gestiona a sus vendedores."""
    if not (
        autor.es_admin
        and vendedor.rol == RolUsuario.VENDEDOR
        and vendedor.id_almacen_id == autor.id_almacen_id
        and autor.pk != vendedor.pk
    ):
        raise ReglaDeNegocioError("No puedes modificar a ese usuario.")


def vendedor_tiene_historial(vendedor):
    """
    True si el vendedor aparece como autor de algo: ventas, anulaciones, movimientos
    de stock o productos creados. Esas filas lo protegen (on_delete=PROTECT): quién
    vendió y quién anuló no se pierde nunca (CU-03).
    """
    return (
        vendedor.ventas.exists()
        or vendedor.ventas_anuladas.exists()
        or vendedor.movimientos_stock.exists()
        or vendedor.productos_creados.exists()
        or vendedor.accesos_reporte.exists()
        or vendedor.alertas_vistas.exists()
    )


MENSAJE_CON_HISTORIAL = (
    "«{nombre}» tiene ventas o movimientos registrados y no se puede eliminar: el "
    "sistema guarda quién hizo cada venta. Desactiva su cuenta para que no pueda ingresar."
)


def eliminar_vendedor(*, autor, vendedor):
    """
    Elimina un vendedor sin historial (p. ej. creado por error). Con historial se
    rechaza y se ofrece desactivarlo. Sus sesiones quedan inválidas al no existir.
    """
    _verificar_gestion_de_vendedor(autor, vendedor)
    if vendedor_tiene_historial(vendedor):
        raise ReglaDeNegocioError(MENSAJE_CON_HISTORIAL.format(nombre=vendedor.nombre))
    id_vendedor, nombre = vendedor.pk, vendedor.nombre
    try:
        with transaction.atomic():
            vendedor.delete()
    except ProtectedError:  # se registró algo entre la revisión y el borrado
        raise ReglaDeNegocioError(MENSAJE_CON_HISTORIAL.format(nombre=nombre)) from None
    registro_seguridad.info(
        "Vendedor eliminado: usuario %s (almacén %s) por usuario %s",
        id_vendedor,
        autor.id_almacen_id,
        autor.pk,
    )
    return nombre


def cambiar_estado_vendedor(*, autor, vendedor, activo):
    """
    Desactiva (no puede ingresar; su sesión abierta se cierra en la siguiente
    solicitud) o reactiva a un vendedor. Sus ventas y movimientos no cambian.
    """
    _verificar_gestion_de_vendedor(autor, vendedor)
    vendedor.is_active = activo
    vendedor.save(update_fields=["is_active"])
    registro_seguridad.info(
        "Vendedor %s: usuario %s (almacén %s) por usuario %s",
        "reactivado" if activo else "desactivado",
        vendedor.pk,
        vendedor.id_almacen_id,
        autor.pk,
    )
    return vendedor
