import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Command(BaseCommand):
    help = (
        "Genera el par de claves VAPID para las notificaciones push e imprime las líneas "
        "para .env. Se hace una sola vez: si se cambian, cada dispositivo tiene que volver "
        "a activar las notificaciones."
    )

    def handle(self, *args, **options):
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, "big")
        public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        self.stdout.write(f"WEBPUSH_VAPID_PUBLIC_KEY={_b64url(public)}")
        self.stdout.write(f"WEBPUSH_VAPID_PRIVATE_KEY={_b64url(private)}")
