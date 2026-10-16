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
