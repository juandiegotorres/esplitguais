"""IP real del cliente para django-axes.

`CF-Connecting-IP` solo se cree si la conexión viene de quien puede haberlo puesto:
- Docker + Cloudflare Tunnel: el contenedor `cloudflared`, en la red privada de Compose.
- cPanel: un borde de Cloudflare (registro DNS proxied apuntando al servidor).

Cualquier otro origen (alguien que le pega directo a la IP del servidor) podría
inventarse el header para esquivar el bloqueo, así que se usa `REMOTE_ADDR`.
"""

from ipaddress import ip_address, ip_network

# https://www.cloudflare.com/ips/ (revisar si Cloudflare publica rangos nuevos).
CLOUDFLARE_NETWORKS = tuple(
    ip_network(net)
    for net in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def _is_trusted_proxy(addr: str) -> bool:
    try:
        ip = ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or any(ip in net for net in CLOUDFLARE_NETWORKS)


def client_ip(request) -> str | None:
    remote_addr = request.META.get("REMOTE_ADDR")
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
    if cf_ip and remote_addr and _is_trusted_proxy(remote_addr):
        return cf_ip
    return remote_addr
