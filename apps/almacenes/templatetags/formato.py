from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def pesos(valor):
    """1990 -> «$1.990». Montos en pesos chilenos, sin decimales."""
    try:
        entero = int(Decimal(valor))
    except (TypeError, ValueError, InvalidOperation):
        return ""
    signo = "-" if entero < 0 else ""
    return f"{signo}${abs(entero):,}".replace(",", ".")


@register.filter
def porcentaje(valor, con_signo=False):
    """12.5 -> «12,5 %»; con `porcentaje:True`, «+12,5 %». Coma decimal, como en Chile."""
    try:
        numero = Decimal(valor)
    except (TypeError, ValueError, InvalidOperation):
        return ""
    signo = "+" if con_signo and numero > 0 else ""
    return f"{signo}{numero:.1f} %".replace(".", ",")


@register.filter
def duracion(valor):
    """timedelta -> «40 s», «1 min 35 s», «3 h 10 min» o «2 días 4 h», redondeado."""
    if valor is None:
        return ""
    segundos = round(valor.total_seconds())
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segundos = divmod(resto, 60)
    if dias:
        texto = f"{dias} día{'s' if dias != 1 else ''}"
        return f"{texto} {horas} h" if horas else texto
    if horas:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    if minutos:
        return f"{minutos} min {segundos} s" if segundos else f"{minutos} min"
    return f"{segundos} s"
