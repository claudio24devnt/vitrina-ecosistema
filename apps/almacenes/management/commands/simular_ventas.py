"""
VENTAS FICTICIAS para demostrar los reportes. No son una medición ni provienen del
almacén piloto: los momentos, las cantidades y los medios de pago son INVENTADOS
con patrones supuestos (más venta el fin de semana, al mediodía y en la tarde). No
usar sobre el almacén piloto ni para estimar indicadores (§2.3 y §7).

Simula ventas desde el día 1 de un mes hasta hoy sobre un almacén EXISTENTE, con
sus propios productos. Todo pasa por los servicios de negocio y después cada
registro se «envejece» a su fecha simulada con un update().

- Autor único: un vendedor desactivado «Venta simulada (ficticia)» (no puede
  entrar). Firma todas las ventas, salidas, entradas y anulaciones simuladas: es la
  marca que permite borrarlas con --deshacer sin cambiar el modelo.
- Suma cero por producto: al inicio de cada mes entra exactamente lo que se vende
  ese mes, así que el stock actual queda igual y no se generan ajustes. Costo
  aceptado: cada producto llega a 0 a fin de mes en la serie de movimientos
  (quiebres artificiales en el indicador).
- `hora_inicio` inventada (20 a 120 s antes de confirmar): el indicador «tiempo de
  registro» de estos meses es ficticio.

Se corre una vez por SSH en el App Service (ver infra/README.md):

    python manage.py simular_ventas --email <admin del almacén> --desde 2026-08
    python manage.py simular_ventas --email <admin del almacén> --desde 2026-08 --confirmar
    python manage.py simular_ventas --email <admin del almacén> --deshacer --confirmar

Sin --confirmar sólo muestra lo que haría (no escribe nada).
"""

import random
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Case, F, IntegerField, Max, Q, Sum, When
from django.utils import timezone

from apps.almacenes.models import ZONA_HORARIA_ALMACEN
from apps.inventario.models import MovimientoStock, Producto, TipoMovimiento
from apps.inventario.servicios import registrar_entrada_stock
from apps.usuarios.models import RolUsuario, Usuario
from apps.usuarios.servicios import crear_vendedor
from apps.ventas.models import DetalleVenta, MedioPago, Venta
from apps.ventas.servicios import (
    LineaVenta,
    StockInsuficienteError,
    anular_venta,
    registrar_venta,
)

NOMBRE_SIMULADO = "Venta simulada (ficticia)"
PLANES_PROHIBIDOS = {"operacion"}
MOTIVO_ANULACION = "Venta simulada anulada"
# Peso relativo por día de la semana (lunes=0) y por hora. Supuestos, no medición.
PESO_DIA = [0.9, 0.8, 0.8, 0.9, 1.15, 1.45, 1.05]
PESO_HORA = {
    7: 3, 8: 6, 9: 5, 10: 4, 11: 5, 12: 8, 13: 8, 14: 4, 15: 3, 16: 3,
    17: 5, 18: 7, 19: 8, 20: 6, 21: 3, 22: 1,
}  # fmt: skip
MEDIOS = [MedioPago.EFECTIVO] * 5 + [MedioPago.DEBITO] * 4 + [MedioPago.TRANSFERENCIA]
PROPORCION_ANULADAS = 0.02


def email_simulado(almacen):
    return f"venta.simulada.{almacen.pk}@simulada.ficticio.test"


def _mes(texto):
    try:
        anio, mes = (int(parte) for parte in texto.split("-"))
        return date(anio, mes, 1)
    except ValueError:
        raise CommandError(
            "--desde debe tener la forma AAAA-MM, por ejemplo 2026-08."
        ) from None


class Command(BaseCommand):
    help = "Simula ventas FICTICIAS en un almacén existente (para demostración)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Administrador del almacén.")
        parser.add_argument("--desde", type=_mes, help="Primer mes, AAAA-MM.")
        parser.add_argument("--ventas-por-dia", type=float, default=12)
        parser.add_argument("--semilla", type=int, default=2026)
        parser.add_argument("--deshacer", action="store_true")
        parser.add_argument("--confirmar", action="store_true", help="Sin esto, sólo ensaya.")

    def handle(self, *args, email, desde, ventas_por_dia, semilla, deshacer, confirmar, **op):
        # Transversal a propósito: el almacén se identifica por su administrador.
        admin = Usuario.sin_aislamiento.filter(email__iexact=email.strip()).first()
        if admin is None or admin.rol != RolUsuario.ADMIN:
            raise CommandError("No hay un administrador con ese correo.")
        almacen = admin.id_almacen
        if almacen.plan in PLANES_PROHIBIDOS:
            raise CommandError(f"No se simulan ventas en un almacén de plan «{almacen.plan}».")
        self.stdout.write(f"Almacén: {almacen.razon_social} (plan «{almacen.plan}»).")

        if deshacer:
            return self._deshacer(almacen, confirmar)
        if desde is None:
            raise CommandError("Indica --desde AAAA-MM.")
        hoy = timezone.localdate(timezone=ZONA_HORARIA_ALMACEN)
        if desde > hoy:
            raise CommandError("--desde no puede ser un mes futuro.")
        if Usuario.sin_aislamiento.filter(email=email_simulado(almacen)).exists():
            raise CommandError("Este almacén ya tiene ventas simuladas. Usa antes --deshacer.")
        productos = list(Producto.objects.del_almacen(almacen).filter(precio__gt=0))
        if not productos:
            raise CommandError("El almacén no tiene productos con precio.")

        plan = self._planificar(productos, desde, hoy, ventas_por_dia, random.Random(semilla))
        cantidad = sum(len(ventas) for ventas in plan.values())
        self.stdout.write(
            f"{cantidad} ventas ficticias en {len(plan)} meses con {len(productos)} productos."
        )
        if not confirmar:
            self.stdout.write("Ensayo: no se escribió nada. Repite con --confirmar.")
            return

        simulado = self._crear_simulado(almacen)
        registradas = 0
        for mes, ventas in plan.items():
            with transaction.atomic():
                registradas += self._registrar_mes(almacen, simulado, ventas)
            self.stdout.write(f"  {mes:%Y-%m}: {len(ventas)} ventas.")
        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {registradas} ventas ficticias. Bórralas con --deshacer."
            )
        )

    def _planificar(self, productos, desde, hoy, ventas_por_dia, azar):
        """Arma en memoria todas las ventas: {mes: [(momento, líneas, medio, anular)]}."""
        horas, pesos_hora = zip(*PESO_HORA.items())
        popularidad = [azar.lognormvariate(0, 0.9) for _ in productos]
        ahora = timezone.now() - timedelta(minutes=5)
        plan = defaultdict(list)
        dia = desde
        while dia <= hoy:
            cantidad = max(0, round(azar.gauss(ventas_por_dia * PESO_DIA[dia.weekday()], 3)))
            if dia == desde:
                cantidad = max(cantidad, 1)  # el primer mes tiene que contar como completo
            for _ in range(cantidad):
                momento = datetime.combine(
                    dia,
                    time(azar.choices(horas, pesos_hora)[0], azar.randrange(60)),
                    tzinfo=ZONA_HORARIA_ALMACEN,
                )
                if momento > ahora:
                    continue
                elegidos = set(azar.choices(productos, popularidad, k=azar.randint(1, 4)))
                lineas = [(p.pk, azar.choice([1, 1, 1, 2, 2, 3])) for p in elegidos]
                anular = azar.random() < PROPORCION_ANULADAS
                plan[dia.replace(day=1)].append(
                    (momento, lineas, azar.choice(MEDIOS), anular, azar.randint(20, 120))
                )
            dia += timedelta(days=1)
        for ventas in plan.values():
            ventas.sort(key=lambda venta: venta[0])
        return dict(plan)

    def _crear_simulado(self, almacen):
        simulado = crear_vendedor(
            almacen=almacen,
            nombre=NOMBRE_SIMULADO,
            email=email_simulado(almacen),
            password=secrets.token_urlsafe(24),
        )
        Usuario.objects.del_almacen(almacen).filter(pk=simulado.pk).update(is_active=False)
        return simulado

    def _registrar_mes(self, almacen, simulado, ventas):
        # Entra lo que se venderá (sin las anuladas, que devuelven su stock): suma cero.
        unidades = Counter()
        for _, lineas, _, anular, _ in ventas:
            if not anular:
                for pk, cantidad in lineas:
                    unidades[pk] += cantidad
        inicio = ventas[0][0] - timedelta(minutes=5)
        productos = Producto.objects.del_almacen(almacen).in_bulk(unidades.keys())
        previo = MovimientoStock.objects.del_almacen(almacen).aggregate(m=Max("pk"))["m"] or 0
        for pk, cantidad in sorted(unidades.items()):
            registrar_entrada_stock(
                almacen=almacen, producto=productos[pk], cantidad=cantidad, usuario=simulado
            )
        MovimientoStock.objects.del_almacen(almacen).filter(
            id_usuario=simulado, pk__gt=previo
        ).update(fecha_hora=inicio)

        registradas = 0
        for momento, lineas, medio, anular, segundos in ventas:
            try:
                venta = registrar_venta(
                    almacen=almacen,
                    usuario=simulado,
                    lineas=[LineaVenta(id_producto=pk, cantidad=c) for pk, c in lineas],
                    medio_pago=medio,
                )
            except StockInsuficienteError:
                # Sólo puede pasarle a una anulada (su stock no se repuso): se omite.
                continue
            cambios = {
                "fecha_hora": momento,
                "hora_inicio": momento - timedelta(seconds=segundos),
            }
            movimientos = MovimientoStock.objects.del_almacen(almacen).filter(id_venta=venta)
            if anular:
                anular_venta(
                    almacen=almacen, venta=venta, usuario=simulado, motivo=MOTIVO_ANULACION
                )
                cambios["fecha_anulacion"] = momento + timedelta(minutes=3)
                movimientos.filter(tipo=TipoMovimiento.ENTRADA).update(
                    fecha_hora=cambios["fecha_anulacion"]
                )
            movimientos.filter(tipo=TipoMovimiento.SALIDA).update(fecha_hora=momento)
            Venta.objects.del_almacen(almacen).filter(pk=venta.pk).update(**cambios)
            registradas += 1
        return registradas

    def _deshacer(self, almacen, confirmar):
        simulado = Usuario.objects.del_almacen(almacen).filter(email=email_simulado(almacen))
        simulado = simulado.first()
        if simulado is None:
            raise CommandError("Este almacén no tiene ventas simuladas.")
        ventas = Venta.objects.del_almacen(almacen).filter(id_usuario=simulado)
        movimientos = MovimientoStock.objects.del_almacen(almacen).filter(
            Q(id_usuario=simulado) | Q(id_venta__in=ventas)
        )
        efecto = movimientos.values("id_producto").annotate(
            neto=Sum(
                Case(
                    When(tipo=TipoMovimiento.SALIDA, then=-F("cantidad")),
                    default=F("cantidad"),
                    output_field=IntegerField(),
                )
            )
        )
        descuadrados = [fila["id_producto"] for fila in efecto if fila["neto"]]
        if descuadrados:
            raise CommandError(
                "Las ventas simuladas no suman cero en los productos "
                f"{descuadrados}: borrarlas cambiaría el stock. No se borró nada."
            )
        self.stdout.write(f"Se borrarían {ventas.count()} ventas simuladas.")
        if not confirmar:
            self.stdout.write("Ensayo: no se borró nada. Repite con --confirmar.")
            return
        with transaction.atomic():
            movimientos.delete()
            DetalleVenta.objects.del_almacen(almacen).filter(id_venta__in=ventas).delete()
            ventas.delete()
            simulado.delete()
        self.stdout.write(self.style.SUCCESS("Ventas simuladas borradas; el stock no cambió."))
