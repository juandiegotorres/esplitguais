import hashlib
import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.views.decorators.http import require_POST, require_safe

from . import push
from .models import PushSubscription

THEME_COLOR = "#070B0B"
BACKGROUND_COLOR = "#070B0B"
SW_VERSION_PLACEHOLDER = "__SW_VERSION__"


@require_safe
def manifest(request):
    data = {
        "id": "/",
        "name": "Esplitiguais",
        "short_name": "Esplitiguais",
        "description": "Gastos compartidos entre amigos.",
        "lang": "es-AR",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": BACKGROUND_COLOR,
        "theme_color": THEME_COLOR,
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {
                "src": static("icons/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    response = JsonResponse(data, content_type="application/manifest+json")
    response["Cache-Control"] = "no-cache"
    return response


@require_safe
def service_worker(request):
    body = render_to_string("pwa/sw.js")
    # La versión del caché sale del propio contenido: cambia si cambia el código
    # del SW o el hash de cualquier estático precacheado.
    version = hashlib.sha256(body.encode()).hexdigest()[:12]
    body = body.replace(SW_VERSION_PLACEHOLDER, version)
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@require_safe
def offline(request):
    # El SW guarda esta página en caché: se renderiza como anónima para no
    # incluir datos de la sesión (usuario, token CSRF, mensajes pendientes).
    context = {"user": AnonymousUser(), "csrf_token": "", "messages": []}
    return render(request, "pwa/offline.html", context)


@require_safe
def install(request):
    return render(request, "pwa/install.html")


def _subscription_from(request) -> dict | None:
    """El JSON de PushSubscription.toJSON() del navegador, validado; None si no sirve."""
    try:
        data = json.loads(request.body)
    except ValueError:
        return None
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, dict):
        return None
    fields = {
        "endpoint": data.get("endpoint"),
        "p256dh": keys.get("p256dh"),
        "auth": keys.get("auth"),
    }
    limits = {name: PushSubscription._meta.get_field(name).max_length for name in fields}
    if not all(isinstance(v, str) and 0 < len(v) <= limits[k] for k, v in fields.items()):
        return None
    return fields if push.is_push_endpoint(fields["endpoint"]) else None


@login_required
@require_POST
def push_subscribe(request):
    fields = _subscription_from(request)
    if fields is None:
        return JsonResponse({"error": "Suscripción inválida."}, status=400)
    # El endpoint es del dispositivo: si otra persona inicia sesión en él, pasa a ser suyo.
    PushSubscription.objects.update_or_create(
        endpoint=fields.pop("endpoint"), defaults={"user": request.user, **fields}
    )
    return HttpResponse(status=204)


@login_required
@require_POST
def push_unsubscribe(request):
    try:
        endpoint = json.loads(request.body)["endpoint"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "Falta el endpoint."}, status=400)
    if not isinstance(endpoint, str):
        return JsonResponse({"error": "Falta el endpoint."}, status=400)
    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return HttpResponse(status=204)
