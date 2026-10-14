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
