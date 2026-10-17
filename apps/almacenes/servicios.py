import re
from datetime import time

from django.db import IntegrityError, transaction

from .errores import ReglaDeNegocioError
from .models import Almacen, FranjaHoraria

# Franjas horarias iniciales del reporte mensual. SUPUESTO, no medición: son el valor
# de partida declarado en el informe, no datos del almacén piloto, y cada almacén las
# puede ajustar a su horario. hora_fin es exclusiva (ver FranjaHoraria).
FRANJAS_INICIALES = [
    ("Mañana", 1, time(7, 0), time(11, 0)),
    ("Mediodía", 2, time(11, 0), time(14, 0)),
    ("Tarde", 3, time(14, 0), time(18, 0)),
    ("Noche", 4, time(18, 0), time(22, 0)),
    ("Resto", 5, time(22, 0), time(7, 0)),
]

# El almacén al que pertenece el operador de la plataforma: el modelo exige que todo
# usuario tenga almacén (usuario.id_almacen NOT NULL). No es un cliente.
PLAN_OPERACION = "operacion"


@transaction.atomic
def crear_almacen(*, razon_social, rut, plan, direccion=None) -> Almacen:
    """Crea el almacén junto con sus franjas horarias iniciales, en una sola transacción."""
    almacen = Almacen.objects.create(
        razon_social=razon_social, rut=rut, plan=plan, direccion=direccion
    )
    FranjaHoraria.objects.bulk_create(
        FranjaHoraria(
            id_almacen=almacen, nombre=nombre, orden=orden, hora_inicio=inicio, hora_fin=fin
        )
        for nombre, orden, inicio, fin in FRANJAS_INICIALES
    )
    return almacen


def _digito_verificador(cuerpo):
    """Módulo 11 del RUT chileno: 11 → «0», 10 → «K»."""
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - suma % 11
    return {11: "0", 10: "K"}.get(resto, str(resto))


def normalizar_rut(texto):
    """
    «76.000.001-1», «76000001-1» o «760000011» → «76000001-1» (sin puntos, guion y DV
    en mayúscula; así se guarda). Lanza ReglaDeNegocioError si el RUT no es válido.
    """
    limpio = re.sub(r"[.\s-]", "", (texto or "")).upper()
    if not re.fullmatch(r"\d{7,8}[\dK]", limpio):
        raise ReglaDeNegocioError(
            "Escribe el RUT con su dígito verificador, p. ej. 76.123.456-7."
        )
    cuerpo, dv = limpio[:-1], limpio[-1]
    if _digito_verificador(cuerpo) != dv:
        raise ReglaDeNegocioError("El RUT no es válido: revisa el dígito verificador.")
    return f"{int(cuerpo)}-{dv}"


def alta_almacen(
    *, razon_social, rut, plan, direccion, nombre_admin, email_admin, password_admin
):
    """
    Alta de un almacén cliente por el operador: el almacén, sus franjas y su primer
    administrador, todo o nada. Desde ahí el administrador crea sus vendedores (CU-06).
    """
    from apps.usuarios.servicios import crear_administrador

    razon_social = (razon_social or "").strip()
    if not razon_social:
        raise ReglaDeNegocioError("Escribe la razón social del almacén.")
    rut = normalizar_rut(rut)
    plan = (plan or "").strip()
    if not plan or plan == PLAN_OPERACION:
        raise ReglaDeNegocioError("Indica el plan del almacén.")
    # Consulta transversal intencional: el RUT es único entre todos los almacenes.
    existente = Almacen.sin_aislamiento.filter(rut=rut).first()
    if existente:
        raise ReglaDeNegocioError(f"Ese RUT ya está registrado: «{existente.razon_social}».")

    try:
        with transaction.atomic():
            almacen = crear_almacen(
                razon_social=razon_social,
                rut=rut,
                plan=plan,
                direccion=(direccion or "").strip() or None,
            )
            administrador = crear_administrador(
                almacen=almacen,
                nombre=nombre_admin,
                email=email_admin,
                password=password_admin,
            )
    except IntegrityError:
        # Otro alta con el mismo RUT entre la consulta y el INSERT.
        raise ReglaDeNegocioError("Ese RUT ya está registrado.") from None
    return almacen, administrador


def almacenes_clientes():
    """
    Todos los almacenes salvo el de operación, para la pantalla del operador.
    Consulta transversal intencional: el operador ve la lista de la plataforma, no
    los datos de cada almacén.
    """
    return Almacen.sin_aislamiento.exclude(plan=PLAN_OPERACION).order_by("-fecha_alta")
