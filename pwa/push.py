"""Envío de notificaciones Web Push.

pywebpush se importa recién al enviar: con CGI cada request arranca Django de cero, y
cargar requests/aiohttp/cryptography en todas las páginas las haría más lentas.
"""

import json
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from django.conf import settings

from .models import PushSubscription

logger = logging.getLogger(__name__)

# El servidor hace un POST a la URL que manda el navegador: solo se aceptan los servicios
# de push conocidos, no cualquier dirección (red interna del hosting, por ejemplo).
PUSH_HOSTS = {"web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com"}
PUSH_HOST_SUFFIXES = (".notify.windows.com",)

# Un celular apagado recibe la notificación cuando vuelve, hasta un día después.
TTL_SECONDS = 24 * 60 * 60
# Se envía mientras la persona espera que se guarde el gasto: no esperar de más a nadie.
TIMEOUT_SECONDS = 5
# El servicio de push dice que el dispositivo ya no existe (desinstaló, revocó el permiso).
GONE_STATUSES = {404, 410}


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    url: str
    # Notificaciones con el mismo tag se reemplazan (editar un gasto no apila avisos).
    tag: str


def enabled() -> bool:
    return bool(
        settings.WEBPUSH_VAPID_PUBLIC_KEY
        and settings.WEBPUSH_VAPID_PRIVATE_KEY
        and settings.WEBPUSH_VAPID_SUBJECT
    )


def is_push_endpoint(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES))


def send(notifications: Mapping[int, Notification]) -> None:
    """Manda a cada ``user_id`` su notificación, a todos sus dispositivos y en paralelo.

    Borra las suscripciones que el servicio de push da por muertas. Nunca lanza: una falla
    de push no puede romper el guardado de un gasto, solo queda en el log.
    """
    if not notifications or not enabled():
        return
    subscriptions = list(PushSubscription.objects.filter(user_id__in=notifications))
    if not subscriptions:
        return

    from pywebpush import WebPushException, webpush

    # Corre en otros hilos: sin consultas a la base (cada hilo abriría su propia conexión).
    def deliver(subscription: PushSubscription) -> int | None:
        """Devuelve el id de la suscripción si hay que borrarla."""
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(asdict(notifications[subscription.user_id])),
                vapid_private_key=settings.WEBPUSH_VAPID_PRIVATE_KEY,
                # pywebpush completa este dict (aud, exp): uno nuevo por envío.
                vapid_claims={"sub": settings.WEBPUSH_VAPID_SUBJECT},
                ttl=TTL_SECONDS,
                timeout=TIMEOUT_SECONDS,
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in GONE_STATUSES:
                return subscription.pk
            logger.warning(
                "Push rechazado (%s) para la suscripción %s: %s", status, subscription.pk, exc
            )
        except Exception:
            # Red caída, timeout, clave VAPID mal copiada: se registra y se sigue.
            logger.exception("No se pudo enviar el push a la suscripción %s", subscription.pk)
        return None

    with ThreadPoolExecutor(max_workers=min(8, len(subscriptions))) as pool:
        gone = [pk for pk in pool.map(deliver, subscriptions) if pk is not None]
    if gone:
        PushSubscription.objects.filter(pk__in=gone).delete()
