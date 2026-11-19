from django import template

register = template.Library()

# Cantidad de colores pastel definidos en app.css (.avatar.tone-1 … .tone-6).
TONES = 6


@register.inclusion_tag("_avatar.html")
def avatar(who, name=None, size=""):
    """Inicial sobre un color fijo por persona (sale del id, así no cambia entre pantallas).

    ``{% avatar user %}`` o ``{% avatar user_id "Ana" %}``; ``size="sm"`` para la versión chica.
    """
    if hasattr(who, "pk"):
        user_id = who.pk
        name = name or who.first_name or who.get_username()
    else:
        user_id = int(who)
    return {"initial": (name or "?")[:1].upper(), "tone": user_id % TONES + 1, "size": size}
