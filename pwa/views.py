import hashlib

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.views.decorators.http import require_safe

THEME_COLOR = "#F7F6F3"
BACKGROUND_COLOR = "#F7F6F3"
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
