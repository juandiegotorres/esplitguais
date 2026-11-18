import sys

from axes.utils import reset as axes_reset
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.passwords import add_password_arguments, read_password, set_validated_password


class Command(BaseCommand):
    help = "Cambia la contraseña de un usuario existente y lo desbloquea si django-axes lo había bloqueado."
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument("username")
        add_password_arguments(parser)

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"].strip()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"El usuario «{username}» no existe.") from None

        password = read_password(options, options.get("stdin", sys.stdin))
        set_validated_password(user, password)
        user.save(update_fields=["password"])
        unlocked = axes_reset(username=user.username)
        self.stdout.write(self.style.SUCCESS(f"Contraseña de «{username}» actualizada."))
        if unlocked:
            self.stdout.write(f"Se borraron {unlocked} registro(s) de intentos fallidos.")
