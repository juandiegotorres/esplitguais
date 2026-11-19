from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Profile


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuario o contraseña incorrectos. Ojo con mayúsculas y minúsculas.",
        "inactive": "Esta cuenta está desactivada.",
    }


class NameForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name"]
        labels = {"first_name": "Nombre"}
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name", "placeholder": "Juan"})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].help_text = (
            "Cómo te ven los demás en los grupos. Si lo dejás vacío se usa tu usuario "
            f"({self.instance.username})."
        )


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["alias"]
        widgets = {
            "alias": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "autocapitalize": "none",
                    "spellcheck": "false",
                    "placeholder": "juan.perez.mp",
                }
            )
        }
        help_texts = {
            "alias": "El de tu banco o billetera virtual. Lo ven los demás miembros de tus grupos "
            "cuando tienen que pagarte. Dejalo vacío para no mostrar ninguno.",
        }
