"""
Períodos del reporte (2026-11-18): semana (lunes a domingo, como la semana ISO), mes y
año. Sólo fechas locales del almacén; la consulta a la base vive en servicios.py.
Un período es [inicio, fin): `fin` es el primer día del período siguiente.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from .models import TipoPeriodo

NOMBRES_MES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
NOMBRES_DIA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Cuántos períodos muestra la comparación, contando el consultado.
EN_COMPARACION = {TipoPeriodo.SEMANA: 8, TipoPeriodo.MES: 6, TipoPeriodo.ANIO: 5}


def mes_siguiente(mes):
    return date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)


def mes_anterior(mes):
    return (mes - timedelta(days=1)).replace(day=1)


def nombre_mes(mes):
    """date(2026, 9, 1) -> «septiembre 2026»."""
    return f"{NOMBRES_MES[mes.month - 1]} {mes.year}"


def _mes_corto(fecha):
    return NOMBRES_MES[fecha.month - 1][:3]


@dataclass(frozen=True)
class Periodo:
    tipo: str
    inicio: date

    @classmethod
    def que_contiene(cls, tipo, fecha):
        if tipo == TipoPeriodo.SEMANA:
            return cls(tipo, fecha - timedelta(days=fecha.weekday()))
        if tipo == TipoPeriodo.MES:
            return cls(tipo, fecha.replace(day=1))
        if tipo == TipoPeriodo.ANIO:
            return cls(tipo, date(fecha.year, 1, 1))
        raise ValueError(f"Tipo de período desconocido: {tipo}")

    @property
    def fin(self):
        if self.tipo == TipoPeriodo.SEMANA:
            return self.inicio + timedelta(days=7)
        if self.tipo == TipoPeriodo.MES:
            return mes_siguiente(self.inicio)
        return date(self.inicio.year + 1, 1, 1)

    @property
    def ultimo_dia(self):
        return self.fin - timedelta(days=1)

    @property
    def anterior(self):
        return Periodo.que_contiene(self.tipo, self.inicio - timedelta(days=1))

    @property
    def siguiente(self):
        return Periodo(self.tipo, self.fin)

    @property
    def valor(self):
        """Texto del parámetro en la URL: 2026-11-09 (lunes), 2026-09 o 2026."""
        if self.tipo == TipoPeriodo.SEMANA:
            return self.inicio.isoformat()
        if self.tipo == TipoPeriodo.MES:
            return f"{self.inicio:%Y-%m}"
        return str(self.inicio.year)

    @property
    def nombre(self):
        """Para frases: «la semana del 7 al 13 de septiembre de 2026», «septiembre 2026»."""
        if self.tipo == TipoPeriodo.MES:
            return nombre_mes(self.inicio)
        if self.tipo == TipoPeriodo.ANIO:
            return str(self.inicio.year)
        ini, fin = self.inicio, self.ultimo_dia
        if ini.year != fin.year:
            return (
                f"la semana del {ini.day} de {NOMBRES_MES[ini.month - 1]} de {ini.year} "
                f"al {fin.day} de {NOMBRES_MES[fin.month - 1]} de {fin.year}"
            )
        if ini.month != fin.month:
            return (
                f"la semana del {ini.day} de {NOMBRES_MES[ini.month - 1]} al {fin.day} de "
                f"{NOMBRES_MES[fin.month - 1]} de {fin.year}"
            )
        mes = NOMBRES_MES[fin.month - 1]
        return f"la semana del {ini.day} al {fin.day} de {mes} de {fin.year}"

    @property
    def etiqueta(self):
        """Corta, para el selector y la tabla: «7 al 13 sep 2026», «Septiembre 2026»."""
        if self.tipo == TipoPeriodo.MES:
            return nombre_mes(self.inicio).capitalize()
        if self.tipo == TipoPeriodo.ANIO:
            return str(self.inicio.year)
        ini, fin = self.inicio, self.ultimo_dia
        if ini.year != fin.year:
            return (
                f"{ini.day} {_mes_corto(ini)} {ini.year} al "
                f"{fin.day} {_mes_corto(fin)} {fin.year}"
            )
        if ini.month != fin.month:
            return f"{ini.day} {_mes_corto(ini)} al {fin.day} {_mes_corto(fin)} {fin.year}"
        return f"{ini.day} al {fin.day} {_mes_corto(fin)} {fin.year}"

    @property
    def titulo(self):
        if self.tipo == TipoPeriodo.ANIO:
            return f"Reporte del año {self.inicio.year}"
        return f"Reporte de {self.nombre}"

    # Concordancia en las frases: «la semana ... no está completa», «el mes anterior».
    @property
    def completo_palabra(self):
        return "completa" if self.tipo == TipoPeriodo.SEMANA else "completo"

    @property
    def cuando_termina(self):
        return {
            TipoPeriodo.SEMANA: "termine la semana",
            TipoPeriodo.MES: "cierre el mes",
            TipoPeriodo.ANIO: "termine el año",
        }[self.tipo]

    @property
    def frente_al_anterior(self):
        return {
            TipoPeriodo.SEMANA: "Frente a la semana anterior",
            TipoPeriodo.MES: "Frente al mes anterior",
            TipoPeriodo.ANIO: "Frente al año anterior",
        }[self.tipo]

    @property
    def anteriores(self):
        return {
            TipoPeriodo.SEMANA: "Semanas anteriores",
            TipoPeriodo.MES: "Meses anteriores",
            TipoPeriodo.ANIO: "Años anteriores",
        }[self.tipo]

    @property
    def en_el_periodo(self):
        return {
            TipoPeriodo.SEMANA: "en la semana",
            TipoPeriodo.MES: "en el mes",
            TipoPeriodo.ANIO: "en el año",
        }[self.tipo]


def leer_periodo(tipo, texto):
    """
    Lee el valor de la URL según el tipo: «2026-11-11» (cualquier día de la semana; se
    lleva al lunes), «2026-09» o «2026». None si el tipo o el texto no son válidos.
    """
    try:
        if tipo == TipoPeriodo.SEMANA:
            return Periodo.que_contiene(tipo, date.fromisoformat(texto))
        if tipo == TipoPeriodo.MES:
            return Periodo(tipo, date.fromisoformat(f"{texto}-01"))
        if tipo == TipoPeriodo.ANIO and len(texto) == 4:
            return Periodo(tipo, date(int(texto), 1, 1))
    except (TypeError, ValueError):
        pass
    return None
