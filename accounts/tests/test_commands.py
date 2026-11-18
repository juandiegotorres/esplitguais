from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

STRONG = "asado-del-domingo-42"


def run(command, *args, stdin_text=None):
    out = StringIO()
    kwargs = {"stdout": out}
    if stdin_text is not None:
        args = (*args, "--password-stdin")
        kwargs["stdin"] = StringIO(stdin_text)
    call_command(command, *args, **kwargs)
    return out.getvalue()


class CrearUsuarioTests(TestCase):
    def test_creates_user_with_hashed_password(self):
        run("crear_usuario", "juan", stdin_text=STRONG + "\n")
        user = User.objects.get(username="juan")
        self.assertNotEqual(user.password, STRONG)
        self.assertTrue(user.check_password(STRONG))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_interactive_prompts_twice(self):
        with mock.patch("accounts.passwords.getpass.getpass", side_effect=[STRONG, STRONG]):
            run("crear_usuario", "ana")
        self.assertTrue(User.objects.get(username="ana").check_password(STRONG))

    def test_interactive_mismatch_fails_without_creating(self):
        with mock.patch("accounts.passwords.getpass.getpass", side_effect=[STRONG, STRONG + "x"]):
            with self.assertRaisesMessage(CommandError, "no coinciden"):
                run("crear_usuario", "ana")
        self.assertFalse(User.objects.filter(username="ana").exists())

    def test_existing_username_is_rejected_case_insensitively(self):
        User.objects.create_user("juan", password=STRONG)
        with self.assertRaisesMessage(CommandError, "ya existe"):
            run("crear_usuario", "Juan", stdin_text=STRONG + "\n")
        self.assertEqual(User.objects.count(), 1)

    def test_weak_password_is_rejected(self):
        for weak in ("1234", "12345678901", "password"):
            with self.subTest(weak=weak), self.assertRaisesMessage(CommandError, "Contraseña rechazada"):
                run("crear_usuario", "juan", stdin_text=weak + "\n")
        self.assertFalse(User.objects.filter(username="juan").exists())

    def test_invalid_username_is_rejected(self):
        with self.assertRaisesMessage(CommandError, "inválido"):
            run("crear_usuario", "juan perez", stdin_text=STRONG + "\n")


class ResetearPasswordTests(TestCase):
    def test_unknown_user_fails(self):
        with self.assertRaisesMessage(CommandError, "no existe"):
            run("resetear_password", "nadie", stdin_text=STRONG + "\n")

    def test_changes_password(self):
        User.objects.create_user("juan", password="vieja-clave-segura-1")
        run("resetear_password", "juan", stdin_text=STRONG + "\n")
        user = User.objects.get(username="juan")
        self.assertTrue(user.check_password(STRONG))
        self.assertFalse(user.check_password("vieja-clave-segura-1"))

    def test_weak_password_keeps_old_one(self):
        User.objects.create_user("juan", password="vieja-clave-segura-1")
        with self.assertRaises(CommandError):
            run("resetear_password", "juan", stdin_text="password\n")
        self.assertTrue(User.objects.get(username="juan").check_password("vieja-clave-segura-1"))

    def test_reset_unlocks_axes_lockout(self):
        User.objects.create_user("juan", password="vieja-clave-segura-1")
        login = reverse("login")
        for _ in range(5):
            self.client.post(login, {"username": "juan", "password": "mal"})
        locked = self.client.post(login, {"username": "juan", "password": "vieja-clave-segura-1"})
        self.assertEqual(locked.status_code, 429)

        run("resetear_password", "juan", stdin_text=STRONG + "\n")

        response = self.client.post(login, {"username": "juan", "password": STRONG})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(username="juan").pk)
