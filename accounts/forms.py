from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuario o contraseña incorrectos. Ojo con mayúsculas y minúsculas.",
        "inactive": "Esta cuenta está desactivada.",
    }
