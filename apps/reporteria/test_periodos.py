"""
Reporte por semana, mes y año; menos vendidos, sin ventas y por categoría (2026-11-18).
Todos los datos son FICTICIOS, creados sólo para pruebas: no provienen del almacén
piloto ni de ningún almacén real.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.almacenes.errores import ReglaDeNegocioError
from apps.almacenes.models import ZONA_HORARIA_ALMACEN
from apps.almacenes.servicios import crear_almacen
from apps.inventario.models import Categoria, Producto
from apps.reporteria.models import AccesoReporte, TipoPeriodo
from apps.reporteria.periodos import Periodo, leer_periodo
from apps.reporteria.servicios import (
    TOPE_MAS_VENDIDOS,
    avisar_cierre_mes,
    consultar_reporte,
    periodo_por_omision,
    periodos_disponibles,
    reporte,
    reporte_mensual,
)
from apps.reporteria.test_servicios import dar_de_alta_en, local, producto_ficticio, vender
from conftest import usuario_de

HOY = date(2026, 10, 16)  # viernes
SEMANA, MES, ANIO = TipoPeriodo.SEMANA, TipoPeriodo.MES, TipoPeriodo.ANIO
SEPTIEMBRE = Periodo(MES, date(2026, 9, 1))


@pytest.fixture
def tienda(almacen):
    return dar_de_alta_en(almacen, date(2026, 1, 1))


def creado_el(producto, fecha):
    Producto.sin_aislamiento.filter(pk=producto.pk).update(
        fecha_creacion=datetime.combine(
            fecha, datetime.min.time(), tzinfo=ZONA_HORARIA_ALMACEN
        )
    )
    return producto


def productos_viejos(tienda, cantidad, prefijo="Ficticio"):
    return [
        creado_el(producto_ficticio(tienda, f"{prefijo} {n:02d}"), date(2026, 1, 1))
        for n in range(cantidad)
    ]


class TestPeriodo:
    @pytest.mark.parametrize(
        "tipo, fecha, inicio, fin",
        [
            (SEMANA, date(2026, 10, 16), date(2026, 10, 12), date(2026, 10, 19)),
            (SEMANA, date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 19)),
            (SEMANA, date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 5)),
            (MES, date(2026, 12, 31), date(2026, 12, 1), date(2027, 1, 1)),
            (ANIO, date(2026, 10, 16), date(2026, 1, 1), date(2027, 1, 1)),
        ],
    )
    def test_inicio_y_fin(self, tipo, fecha, inicio, fin):
        periodo = Periodo.que_contiene(tipo, fecha)
        assert (periodo.inicio, periodo.fin) == (inicio, fin)
        assert periodo.anterior.fin == periodo.inicio
        assert periodo.siguiente.inicio == periodo.fin

    def test_tipo_desconocido(self):
        with pytest.raises(ValueError):
            Periodo.que_contiene("quincena", HOY)

    @pytest.mark.parametrize(
        "inicio, nombre, etiqueta",
        [
            (
                date(2026, 9, 7),
                "la semana del 7 al 13 de septiembre de 2026",
                "7 al 13 sep 2026",
            ),
            (
                date(2026, 9, 28),
                "la semana del 28 de septiembre al 4 de octubre de 2026",
                "28 sep al 4 oct 2026",
            ),
            (
                date(2025, 12, 29),
                "la semana del 29 de diciembre de 2025 al 4 de enero de 2026",
                "29 dic 2025 al 4 ene 2026",
            ),
        ],
    )
    def test_nombres_de_la_semana(self, inicio, nombre, etiqueta):
        semana = Periodo(SEMANA, inicio)
        assert (semana.nombre, semana.etiqueta) == (nombre, etiqueta)
        assert semana.titulo == f"Reporte de {nombre}"

    def test_nombres_del_mes_y_del_anio(self):
        assert (SEPTIEMBRE.nombre, SEPTIEMBRE.etiqueta) == (
            "septiembre 2026",
            "Septiembre 2026",
        )
        anio = Periodo(ANIO, date(2026, 1, 1))
        assert (anio.nombre, anio.etiqueta, anio.titulo) == (
            "2026",
            "2026",
            "Reporte del año 2026",
        )

    @pytest.mark.parametrize(
        "tipo, texto, inicio",
        [
            (SEMANA, "2026-10-14", date(2026, 10, 12)),  # miércoles -> su lunes
            (MES, "2026-09", date(2026, 9, 1)),
            (ANIO, "2026", date(2026, 1, 1)),
        ],
    )
    def test_leer_valido(self, tipo, texto, inicio):
        periodo = leer_periodo(tipo, texto)
        assert periodo.inicio == inicio
        assert leer_periodo(tipo, periodo.valor) == periodo

    @pytest.mark.parametrize(
        "tipo, texto",
        [
            (SEMANA, "2026-13-01"),
            (SEMANA, None),
            (MES, "2026-9-1"),
            (ANIO, "26"),
            (ANIO, "dos mil"),
            ("quincena", "2026"),
        ],
    )
    def test_leer_invalido(self, tipo, texto):
        assert leer_periodo(tipo, texto) is None


@pytest.mark.django_db
class TestMenosVendidos:
    def test_no_repite_los_mas_vendidos(self, tienda):
        productos = productos_viejos(tienda, TOPE_MAS_VENDIDOS + 3)
        for unidades, producto in enumerate(productos, start=1):
            vender(tienda, local(2026, 9, 10, 10), (producto, unidades))
        resultado = reporte_mensual(tienda, SEPTIEMBRE.inicio, HOY)
        assert len(resultado.mas_vendidos) == TOPE_MAS_VENDIDOS
        assert [f["unidades"] for f in resultado.menos_vendidos] == [1, 2, 3]
        assert resultado.productos_vendidos == TOPE_MAS_VENDIDOS + 3
        assert resultado.menos_vendidos[0]["stock_actual"] == 0

    def test_con_pocos_productos_queda_vacia(self, tienda):
        (producto,) = productos_viejos(tienda, 1)
        vender(tienda, local(2026, 9, 10, 10), (producto, 1))
        resultado = reporte_mensual(tienda, SEPTIEMBRE.inicio, HOY)
        assert resultado.menos_vendidos == []
        assert resultado.productos_vendidos == 1


@pytest.mark.django_db
class TestSinVentas:
    def test_lista_los_que_no_se_vendieron_por_stock(self, tienda):
        vendido, quieto, mas_quieto = productos_viejos(tienda, 3)
        Producto.sin_aislamiento.filter(pk=quieto.pk).update(stock_actual=2)
        Producto.sin_aislamiento.filter(pk=mas_quieto.pk).update(stock_actual=5)
        vender(tienda, local(2026, 9, 10, 10), (vendido, 1))
        vender(tienda, local(2026, 8, 10, 10), (quieto, 1))  # otro mes: no cuenta
        resultado = reporte_mensual(tienda, SEPTIEMBRE.inicio, HOY).sin_ventas
        assert [f["nombre"] for f in resultado["productos"]] == [
            mas_quieto.nombre,
            quieto.nombre,
        ]
        assert (resultado["cantidad"], resultado["unidades"]) == (2, 7)
        assert resultado["valor"] == Decimal("7000")  # 7 unidades a $1.000
        assert not any(f["nuevo"] for f in resultado["productos"])

    def test_una_venta_anulada_no_cuenta_como_venta(self, tienda):
        from apps.ventas.servicios import anular_venta

        vendido, anulado = productos_viejos(tienda, 2)
        vender(tienda, local(2026, 9, 10, 10), (vendido, 1))
        venta = vender(tienda, local(2026, 9, 11, 10), (anulado, 1))
        anular_venta(
            almacen=tienda,
            venta=venta,
            usuario=usuario_de(tienda),
            motivo="Error de digitación",
            momento=local(2026, 9, 11, 10, 5),
        )
        filas = reporte_mensual(tienda, SEPTIEMBRE.inicio, HOY).sin_ventas["productos"]
        assert [f["nombre"] for f in filas] == [anulado.nombre]

    def test_marca_los_nuevos_y_omite_los_posteriores(self, tienda):
        (vendido,) = productos_viejos(tienda, 1)
        creado_el(producto_ficticio(tienda, "Nuevo Ficticio"), date(2026, 9, 20))
        creado_el(producto_ficticio(tienda, "Futuro Ficticio"), date(2026, 10, 2))
        vender(tienda, local(2026, 9, 10, 10), (vendido, 1))
        (fila,) = reporte_mensual(tienda, SEPTIEMBRE.inicio, HOY).sin_ventas["productos"]
        assert (fila["nombre"], fila["nuevo"], fila["alta"]) == (
            "Nuevo Ficticio",
            True,
            date(2026, 9, 20),
        )


@pytest.mark.django_db
class TestPorCategoria:
    def test_suma_por_categoria_y_aparte_sin_categoria(self, tienda):
        bebidas = Categoria.objects.del_almacen(tienda).create(nombre="Bebidas")
        bebida = producto_ficticio(
            tienda, "Bebida Ficticia", precio=1500, id_categoria=bebidas
        )
        suelto = producto_ficticio(tienda, "Suelto Ficticio", precio=500)
        vender(tienda, local(2026, 9, 10, 10), (bebida, 2), (suelto, 2))
        filas = reporte_mensual(tienda, SEPTIEMBRE.inicio, HOY).por_categoria
        assert [(f["categoria"], f["monto"], f["participacion"]) for f in filas] == [
            ("Bebidas", Decimal("3000"), Decimal("75.0")),
            ("Sin categoría", Decimal("1000"), Decimal("25.0")),
        ]
        assert [f["sin_categoria"] for f in filas] == [False, True]


@pytest.mark.django_db
class TestReporteSemanal:
    def test_siete_dias_rotulados_sin_dia_de_la_semana(self, tienda):
        producto = producto_ficticio(tienda)
        vender(tienda, local(2026, 9, 7, 10), (producto, 2))  # lunes
        vender(tienda, local(2026, 9, 13, 23, 30), (producto, 1))  # domingo, hora local
        vender(tienda, local(2026, 9, 14, 0, 30), (producto, 5))  # semana siguiente
        resultado = reporte(tienda, Periodo(SEMANA, date(2026, 9, 7)), HOY)
        assert resultado.cantidad_ventas == 2 and resultado.unidades == 3
        assert [b["rotulo"] for b in resultado.grafico["barras"]] == [
            "lun 7",
            "mar 8",
            "mié 9",
            "jue 10",
            "vie 11",
            "sáb 12",
            "dom 13",
        ]
        assert resultado.por_dia_semana == []
        assert resultado.ticket_promedio == Decimal("1500")

    def test_compara_con_la_semana_anterior(self, tienda):
        producto = producto_ficticio(tienda)
        vender(tienda, local(2026, 8, 31, 10), (producto, 2))
        vender(tienda, local(2026, 9, 7, 10), (producto, 3))
        resultado = reporte(tienda, Periodo(SEMANA, date(2026, 9, 7)), HOY)
        assert resultado.variacion == Decimal("50.0")
        assert len(resultado.comparacion) == 8
        assert resultado.comparacion[-2]["inicio"] == date(2026, 8, 31)

    def test_semana_en_curso_lo_dice(self, tienda):
        vender(tienda, local(2026, 10, 13, 10), (producto_ficticio(tienda), 1))
        resultado = reporte(tienda, Periodo.que_contiene(SEMANA, HOY), HOY)
        assert resultado.en_curso and resultado.hasta == date(2026, 10, 17)
        assert resultado.motivo_sin_comparacion == (
            "La semana del 12 al 18 de octubre de 2026 todavía no termina: la comparación "
            "con la semana del 5 al 11 de octubre de 2026 se muestra cuando termine la semana."
        )

    def test_semana_en_que_empezo_el_almacen(self, almacen):
        tienda = dar_de_alta_en(almacen, date(2026, 9, 9))
        vender(tienda, local(2026, 9, 10, 10), (producto_ficticio(tienda), 1))
        resultado = reporte(tienda, Periodo(SEMANA, date(2026, 9, 7)), HOY)
        assert resultado.desde == date(2026, 9, 9) and resultado.mes_parcial
        assert "no está completa y no se compara" in resultado.motivo_sin_comparacion

    def test_semana_base_incompleta(self, almacen):
        tienda = dar_de_alta_en(almacen, date(2026, 9, 2))
        producto = producto_ficticio(tienda)
        vender(tienda, local(2026, 9, 3, 10), (producto, 1))
        vender(tienda, local(2026, 9, 8, 10), (producto, 1))
        resultado = reporte(tienda, Periodo(SEMANA, date(2026, 9, 7)), HOY)
        assert resultado.motivo_sin_comparacion.endswith(
            "la semana del 31 de agosto al 6 de septiembre de 2026 no está completa y no "
            "sirve como base."
        )


@pytest.mark.django_db
class TestReporteAnual:
    def test_barras_por_mes_hasta_hoy(self, tienda):
        producto = producto_ficticio(tienda)
        vender(tienda, local(2026, 3, 10, 10), (producto, 1))
        vender(tienda, local(2026, 9, 10, 10), (producto, 4))
        resultado = reporte(tienda, Periodo(ANIO, date(2026, 1, 1)), HOY)
        assert resultado.por_mes
        barras = resultado.grafico["barras"]
        assert [b["rotulo"] for b in barras][:3] == ["ene", "feb", "mar"]
        assert len(barras) == 10  # enero a octubre: noviembre no ha llegado
        assert resultado.grafico["dias_mayores"] == "septiembre 2026"
        assert len(resultado.por_dia_semana) == 7

    def test_sin_anio_anterior_no_compara(self, tienda):
        vender(tienda, local(2026, 3, 10, 10), (producto_ficticio(tienda), 1))
        resultado = reporte(tienda, Periodo(ANIO, date(2026, 1, 1)), HOY)
        assert resultado.motivo_sin_comparacion.startswith("2026 todavía no termina")
        assert [f["inicio"] for f in resultado.comparacion] == [date(2026, 1, 1)]

    def test_compara_anios_completos(self, almacen):
        tienda = dar_de_alta_en(almacen, date(2024, 1, 1))
        producto = producto_ficticio(tienda)
        vender(tienda, local(2024, 6, 1, 10), (producto, 4))
        vender(tienda, local(2025, 6, 1, 10), (producto, 2))
        resultado = reporte(tienda, Periodo(ANIO, date(2025, 1, 1)), HOY)
        assert resultado.variacion == Decimal("-50.0")


@pytest.mark.django_db
class TestPeriodosDisponibles:
    def test_desde_el_inicio_hasta_hoy(self, almacen):
        tienda = dar_de_alta_en(almacen, date(2026, 9, 30))
        semanas = periodos_disponibles(tienda, SEMANA, HOY)
        assert (semanas[0].inicio, semanas[-1].inicio) == (
            date(2026, 10, 12),
            date(2026, 9, 28),
        )
        assert [p.inicio for p in periodos_disponibles(tienda, ANIO, HOY)] == [
            date(2026, 1, 1)
        ]

    def test_por_omision_el_ultimo_cerrado_si_existe(self, almacen):
        tienda = dar_de_alta_en(almacen, date(2026, 3, 1))
        assert periodo_por_omision(tienda, SEMANA, HOY).inicio == date(2026, 10, 5)
        assert periodo_por_omision(tienda, ANIO, HOY).inicio == date(2026, 1, 1)  # 2025 no
        assert periodo_por_omision(tienda, MES, HOY).inicio == date(2026, 9, 1)

    def test_semana_por_omision_de_un_almacen_recien_creado(self, almacen):
        tienda = dar_de_alta_en(almacen, date(2026, 10, 14))
        assert periodo_por_omision(tienda, SEMANA, HOY).inicio == date(2026, 10, 12)


@pytest.mark.django_db
class TestAccesoConPeriodo:
    def test_registra_el_tipo_y_el_primer_dia(self, tienda):
        admin = usuario_de(tienda)
        consultar_reporte(
            almacen=tienda, usuario=admin, periodo=Periodo(SEMANA, date(2026, 9, 7)), hoy=HOY
        )
        acceso = AccesoReporte.objects.del_almacen(tienda).get()
        assert (acceso.tipo_periodo, acceso.mes_consultado) == (SEMANA, date(2026, 9, 7))

    def test_semanal_no_da_por_visto_el_cierre_de_mes(self, tienda):
        vender(tienda, local(2026, 9, 10, 10), (producto_ficticio(tienda), 1))
        aviso, _ = avisar_cierre_mes(tienda, date(2026, 10, 1))
        consultar_reporte(
            almacen=tienda,
            usuario=usuario_de(tienda),
            periodo=Periodo(SEMANA, date(2026, 8, 31)),  # empieza en agosto, toca septiembre
            hoy=HOY,
        )
        aviso.refresh_from_db()
        assert aviso.fecha_vista is None

    def test_periodo_futuro_no_registra(self, tienda):
        with pytest.raises(ReglaDeNegocioError, match="todavía no empieza"):
            consultar_reporte(
                almacen=tienda,
                usuario=usuario_de(tienda),
                periodo=Periodo(ANIO, date(2027, 1, 1)),
                hoy=HOY,
            )
        assert not AccesoReporte.objects.del_almacen(tienda).exists()

    @pytest.mark.parametrize(
        "tipo, dia",
        [(SEMANA, date(2026, 9, 8)), (MES, date(2026, 9, 2)), (ANIO, date(2026, 2, 1))],
    )
    def test_la_base_rechaza_un_primer_dia_que_no_calza(self, tienda, tipo, dia):
        with pytest.raises(IntegrityError), transaction.atomic():
            AccesoReporte.objects.del_almacen(tienda).create(
                id_usuario=usuario_de(tienda), mes_consultado=dia, tipo_periodo=tipo
            )


@pytest.mark.django_db
class TestAislamientoDelReporte:
    """Las secciones nuevas no mezclan ventas, productos ni categorías de otro almacén."""

    @staticmethod
    def poblar(almacen, prefijo, cantidad):
        categoria = Categoria.objects.del_almacen(almacen).create(nombre=f"{prefijo} cat")
        vendidos = [
            creado_el(
                producto_ficticio(almacen, f"{prefijo} {n:02d}", id_categoria=categoria),
                date(2026, 1, 1),
            )
            for n in range(TOPE_MAS_VENDIDOS + 2)  # alcanza para que haya menos vendidos
        ]
        creado_el(producto_ficticio(almacen, f"{prefijo} quieto"), date(2026, 1, 1))
        for n, producto in enumerate(vendidos, start=1):
            vender(almacen, local(2026, 9, 8, 10), (producto, n * cantidad))
        return {p.nombre for p in vendidos} | {f"{prefijo} quieto"}

    @pytest.mark.parametrize(
        "periodo",
        [
            Periodo(SEMANA, date(2026, 9, 7)),
            SEPTIEMBRE,
            Periodo(ANIO, date(2026, 1, 1)),
        ],
    )
    def test_cada_seccion_ve_solo_su_almacen(self, tienda, periodo):
        ajeno = dar_de_alta_en(
            crear_almacen(
                razon_social="Almacén Ficticio Ajeno", rut="76000003-3", plan="basico"
            ),
            date(2026, 1, 1),
        )
        propios = self.poblar(tienda, "Propio", 1)
        self.poblar(ajeno, "Ajeno", 10)  # vende más: si se colara, encabezaría todo

        resultado = reporte(tienda, periodo, HOY)
        nombres = {
            f["nombre"]
            for f in resultado.mas_vendidos
            + resultado.menos_vendidos
            + resultado.sin_ventas["productos"]
        }
        assert resultado.menos_vendidos
        assert nombres == propios
        assert {f["categoria"] for f in resultado.por_categoria} == {"Propio cat"}
        assert resultado.unidades == sum(range(1, TOPE_MAS_VENDIDOS + 3))
        assert resultado.cantidad_ventas == TOPE_MAS_VENDIDOS + 2
        assert resultado.sin_ventas["cantidad"] == 1
