"""IP real del cliente para django-axes.

En producción la app no publica puertos: solo la alcanza el contenedor `cloudflared`,
y Cloudflare pone la IP original en `CF-Connecting-IP`. Sin ese header (desarrollo
local en 127.0.0.1) se usa `REMOTE_ADDR`.
"""


def client_ip(request) -> str | None:
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
    return cf_ip or request.META.get("REMOTE_ADDR")
