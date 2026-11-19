from django.conf import settings
from django.db import models


class PushSubscription(models.Model):
    """Un dispositivo (navegador o app instalada) que aceptó recibir notificaciones."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    # Lo arma el servicio de push del navegador (Apple, Google, Mozilla); identifica al dispositivo.
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "suscripción a notificaciones"
        verbose_name_plural = "suscripciones a notificaciones"

    def __str__(self) -> str:
        return f"{self.user} · {self.endpoint[:60]}"
