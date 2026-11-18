"""Lectura y validación de contraseñas para los comandos de administración."""

import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError


def add_password_arguments(parser) -> None:
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Lee la contraseña de la primera línea de la entrada estándar (para scripts).",
    )


def read_password(options, stdin) -> str:
    if options["password_stdin"]:
        password = stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Contraseña: ")
        if getpass.getpass("Repetí la contraseña: ") != password:
            raise CommandError("Las contraseñas no coinciden.")
    if not password:
        raise CommandError("La contraseña no puede estar vacía.")
    return password


def set_validated_password(user, password: str) -> None:
    """Valida con AUTH_PASSWORD_VALIDATORS y guarda el hash (no guarda el usuario)."""
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise CommandError("Contraseña rechazada:\n- " + "\n- ".join(exc.messages)) from exc
    user.set_password(password)
