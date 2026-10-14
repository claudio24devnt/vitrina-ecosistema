"""
El esquema real de PostgreSQL coincide con el modelo físico del brief (§3):
tipos, nulabilidad, defaults, restricciones e índices con nombre.
"""

import pytest
from django.db import connection

# tabla -> {columna: (tipo, admite_null)}
COLUMNAS = {
    "almacen": {
        "id_almacen": ("bigint", False),
        "razon_social": ("character varying(120)", False),
        "rut": ("character varying(12)", False),
        "direccion": ("character varying(200)", True),
        "plan": ("character varying(20)", False),
        "fecha_alta": ("timestamp with time zone", False),
        "activo": ("boolean", False),
        "hora_limite_anulacion": ("time without time zone", False),
    },
    "usuario": {
        "id_usuario": ("bigint", False),
        "id_almacen": ("bigint", False),
        "nombre": ("character varying(120)", False),
        "email": ("character varying(150)", False),
        "hash_password": ("character varying(128)", False),
        "rol": ("character varying(10)", False),
        "fecha_creacion": ("timestamp with time zone", False),
    },
    "categoria": {
        "id_categoria": ("bigint", False),
        "id_almacen": ("bigint", False),
        "nombre": ("character varying(80)", False),
    },
    "producto": {
        "id_producto": ("bigint", False),
        "id_almacen": ("bigint", False),
        "id_categoria": ("bigint", True),
        "codigo_barras": ("character varying(20)", False),
        "nombre": ("character varying(150)", False),
        "precio": ("numeric(10,0)", False),
        "stock_actual": ("integer", False),
        "stock_minimo": ("integer", False),
        "fecha_creacion": ("timestamp with time zone", False),
    },
    "venta": {
        "id_venta": ("bigint", False),
        "id_almacen": ("bigint", False),
        "id_usuario": ("bigint", False),
        "fecha_hora": ("timestamp with time zone", False),
        "hora_inicio": ("timestamp with time zone", True),
        "total": ("numeric(12,0)", False),
        "medio_pago": ("character varying(20)", False),
        "estado": ("character varying(10)", False),
        "id_usuario_anulacion": ("bigint", True),
        "motivo_anulacion": ("character varying(200)", True),
        "fecha_anulacion": ("timestamp with time zone", True),
    },
    "detalle_venta": {
        "id_detalle": ("bigint", False),
        "id_almacen": ("bigint", False),
        "id_venta": ("bigint", False),
        "id_producto": ("bigint", False),
        "cantidad": ("integer", False),
        "precio_unitario": ("numeric(10,0)", False),
        "subtotal": ("numeric(12,0)", False),
    },
    "movimiento_stock": {
        "id_movimiento": ("bigint", False),
        "id_almacen": ("bigint", False),
        "id_producto": ("bigint", False),
        "id_venta": ("bigint", True),
        "tipo": ("character varying(10)", False),
        "cantidad": ("integer", False),
        "fecha_hora": ("timestamp with time zone", False),
    },
    "acceso_reporte": {
        "id_acceso": ("bigint", False),
        "id_almacen": ("bigint", False),
        "id_usuario": ("bigint", False),
        "mes_consultado": ("date", False),
        "fecha_hora": ("timestamp with time zone", False),
    },
    "franja_horaria": {
        "id_franja": ("bigint", False),
        "id_almacen": ("bigint", False),
        "nombre": ("character varying(20)", False),
        "orden": ("smallint", False),
        "hora_inicio": ("time without time zone", False),
        "hora_fin": ("time without time zone", False),
    },
}

RESTRICCIONES = {
    "uq_almacen_rut",
    "uq_usuario_email",
    "ck_usuario_rol",
    "uq_categoria",
    "uq_producto",
    "ck_producto_stock_actual",
    "ck_venta_estado",
    "ck_venta_anulacion_coherente",
    "ck_venta_anulacion_posterior",
    "ck_detalle_venta_cantidad",
    "ck_movimiento_stock_tipo",
    "uq_franja_almacen_nombre",
    "uq_franja_almacen_orden",
}

INDICES = {
    "ix_usuario_almacen",
    "ix_producto_codigo",
    "ix_venta_fecha",
    "ix_venta_anuladas",
    "ix_detalle_venta",
    "ix_mov_prod_fecha",
    "ix_acceso_almacen_fecha",
    "ix_franja_almacen",
}


def _consultar(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


@pytest.mark.django_db
@pytest.mark.parametrize("tabla", list(COLUMNAS))
def test_columnas_literales(tabla):
    filas = _consultar(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
        FROM pg_attribute a
        WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
        """,
        [tabla],
    )
    reales = {nombre: (tipo, nulo) for nombre, tipo, nulo in filas}
    for columna, esperado in COLUMNAS[tabla].items():
        assert reales.get(columna) == esperado, f"{tabla}.{columna}"


@pytest.mark.django_db
def test_restricciones_con_nombre():
    nombres = {fila[0] for fila in _consultar("SELECT conname FROM pg_constraint")}
    assert RESTRICCIONES <= nombres


@pytest.mark.django_db
def test_indices_con_nombre():
    nombres = {
        fila[0]
        for fila in _consultar("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
    }
    assert INDICES <= nombres


@pytest.mark.django_db
def test_indice_de_anuladas_es_parcial():
    (definicion,) = _consultar(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_venta_anuladas'"
    )[0]
    assert "WHERE" in definicion and "anulada" in definicion


@pytest.mark.django_db
def test_defaults_en_la_base_de_datos():
    """Un INSERT directo (sin Django) recibe los DEFAULT del modelo físico."""
    (fila,) = _consultar("""
        INSERT INTO almacen (razon_social, rut, plan) VALUES ('Ficticio SQL', '1-9', 'basico')
        RETURNING activo, fecha_alta IS NOT NULL, hora_limite_anulacion::text
        """)
    assert fila == (True, True, "23:59:00")
