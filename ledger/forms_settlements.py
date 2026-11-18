from django import forms
from django.core.exceptions import ValidationError

from . import services


def display_name(user) -> str:
    return user.first_name or user.username


class SettlementForm(forms.Form):
    from_user = forms.TypedChoiceField(label="Quién pagó", coerce=int)
    to_user = forms.TypedChoiceField(label="A quién", coerce=int)
    amount = forms.CharField(
        label="Importe",
        widget=forms.TextInput(
            attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "0,00"}
        ),
    )
    date = forms.DateField(
        label="Fecha", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    note = forms.CharField(label="Nota", required=False, max_length=200)

    # Campos de services.create_settlement → campos del formulario.
    SERVICE_FIELDS = {
        "from_user_id": "from_user",
        "from_user": "from_user",
        "to_user_id": "to_user",
        "to_user": "to_user",
        "amount_cents": "amount",
        "date": "date",
        "note": "note",
    }

    def __init__(self, *args, members, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "Elegí…")] + [(u.pk, display_name(u)) for u in members]
        self.fields["from_user"].choices = choices
        self.fields["to_user"].choices = choices

    def clean_amount(self) -> int:
        try:
            return services.parse_amount(self.cleaned_data["amount"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("from_user") is not None and cleaned.get("from_user") == cleaned.get("to_user"):
            self.add_error("to_user", "Tiene que ser otra persona.")
        return cleaned

    def add_service_errors(self, exc: ValidationError) -> None:
        if hasattr(exc, "error_dict"):
            for key, errors in exc.message_dict.items():
                self.add_error(self.SERVICE_FIELDS.get(key), errors)
        else:
            self.add_error(None, exc.messages)
