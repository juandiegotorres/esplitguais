import sys

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.passwords import add_password_arguments, read_password, set_validated_password


class Command(BaseCommand):
    help = "Crea un usuario común. Pide la contraseña dos veces."
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument("username")
        add_password_arguments(parser)

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"].strip()
        try:
            User.username_validator(username)
        except ValidationError as exc:
            raise CommandError(f"Nombre de usuario inválido: {' '.join(exc.messages)}") from exc
        # Insensible a mayúsculas: "Juan" y "juan" serían dos cuentas confusas para el grupo.
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"El usuario «{username}» ya existe. Usá resetear_password para cambiarle la contraseña.")

        user = User(username=username)
        password = read_password(options, options.get("stdin", sys.stdin))
        set_validated_password(user, password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Usuario «{username}» creado."))
