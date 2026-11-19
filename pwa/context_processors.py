from django.conf import settings

from . import push


def push_settings(request):
    """Clave pública VAPID para activar notificaciones; vacía si están apagadas."""
    return {"push_public_key": settings.WEBPUSH_VAPID_PUBLIC_KEY if push.enabled() else ""}
