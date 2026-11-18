from django import template

from ledger.services import format_amount_input, format_ars

register = template.Library()


@register.filter
def ars(cents):
    """{{ cents|ars }} → "$ 1.234,56" con espacio duro (el monto no se corta); vacío si None o ""."""
    if cents is None or cents == "":
        return ""
    return format_ars(int(cents)).replace(" ", "\u00a0")


@register.filter
def ars_input(cents):
    """{{ cents|ars_input }} → "1.234,56" para prellenar inputs."""
    if cents is None or cents == "":
        return ""
    return format_amount_input(int(cents))
