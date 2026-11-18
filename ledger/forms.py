from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import services
from .models import Category, SplitType

User = get_user_model()

PAYER_SINGLE = "single"
PAYER_MULTIPLE = "multiple"
PAYER_MODE_CHOICES = [
    (PAYER_SINGLE, "Pagó una persona"),
    (PAYER_MULTIPLE, "Pagaron varios"),
]


def display_name(user) -> str:
    return user.get_full_name() or user.username


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return display_name(obj)


class UserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return display_name(obj)


class GroupCreateForm(forms.Form):
    name = forms.CharField(label="Nombre", max_length=100)
    members = UserMultipleChoiceField(
        label="Miembros",
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["members"].queryset = (
            User.objects.filter(is_active=True).exclude(pk=actor.pk).order_by("username")
        )


class AddMemberForm(forms.Form):
    user = UserChoiceField(label="Agregar miembro", queryset=User.objects.none(), empty_label=None)

    def __init__(self, *args, group, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            User.objects.filter(is_active=True)
            .exclude(memberships__group=group)
            .order_by("username")
        )


def format_decimal(value) -> str:
    """Decimal("33.3300") → "33,33"; Decimal("2.0000") → "2"."""
    text = format(Decimal(value).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _parse_decimal(text: str) -> Decimal | None:
    """Valor de porcentaje o partes. Vacío o cero → None (no participa)."""
    text = text.strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValidationError("Ingresá un número válido.")
    if not value.is_finite():
        raise ValidationError("Ingresá un número válido.")
    if value < 0:
        raise ValidationError("No puede ser negativo.")
    if value.as_tuple().exponent < -4:
        raise ValidationError("Como máximo 4 decimales.")
    if value == 0:
        return None
    return value


def _parse_optional_amount(text: str) -> int | None:
    """Importe por miembro. Vacío o cero → None (no participa)."""
    text = text.strip()
    if not text or text.strip("$ 0.,") == "":
        return None
    return services.parse_amount(text)


class ExpenseForm(forms.Form):
    """Formulario de gasto. Los campos por miembro se generan dinámicamente:

    payer_amount_<id>  importe pagado (modo "Pagaron varios")
    exact_<id>         importe exacto adeudado
    percent_<id>       porcentaje
    units_<id>         cantidad de partes
    """

    description = forms.CharField(label="Descripción", max_length=200)
    amount = forms.CharField(
        label="Importe",
        max_length=40,
        widget=forms.TextInput(
            attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "15.000,50"}
        ),
    )
    date = forms.DateField(label="Fecha", widget=forms.DateInput(attrs={"type": "date"}))
    category = forms.ChoiceField(label="Categoría", choices=Category.choices)
    payer_mode = forms.ChoiceField(choices=PAYER_MODE_CHOICES)
    payer = forms.TypedChoiceField(label="Quién pagó", coerce=int, required=False)
    split_type = forms.ChoiceField(label="Reparto", choices=SplitType.choices)
    participants = forms.TypedMultipleChoiceField(coerce=int, required=False)

    def __init__(self, *args, members, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.members = list(members)
        self.section_errors: dict[str, list[str]] = {"payers": [], "shares": []}
        member_choices = [(m.pk, display_name(m)) for m in self.members]
        self.fields["payer"].choices = member_choices
        self.fields["participants"].choices = member_choices
        for m in self.members:
            for prefix in ("payer_amount", "exact", "percent", "units"):
                self.fields[f"{prefix}_{m.pk}"] = forms.CharField(required=False, max_length=40)
        self.fields["date"].widget.format = "%Y-%m-%d"
        self.initial.setdefault("date", timezone.localdate())
        self.initial.setdefault("category", Category.GENERAL)
        self.initial.setdefault("payer_mode", PAYER_SINGLE)
        self.initial.setdefault("payer", actor.pk)
        self.initial.setdefault("split_type", SplitType.EQUAL)
        self.initial.setdefault("participants", [m.pk for m in self.members])
        for m in self.members:
            self.initial.setdefault(f"units_{m.pk}", "1")
        # Atributos de Alpine para los campos que se renderizan con widgets de Django.
        self.fields["amount"].widget.attrs["x-model"] = "amount"
        self.fields["payer"].widget.attrs["x-model"] = "singlePayer"

    @staticmethod
    def initial_from_expense(expense, members) -> dict:
        payers = list(expense.payers.all())
        shares = list(expense.shares.all())
        initial = {
            "description": expense.description,
            "amount": services.format_amount_input(expense.amount_cents),
            "date": expense.date,
            "category": expense.category,
            "split_type": expense.split_type,
        }
        if len(payers) == 1:
            initial["payer_mode"] = PAYER_SINGLE
            initial["payer"] = payers[0].user_id
        else:
            initial["payer_mode"] = PAYER_MULTIPLE
            for p in payers:
                initial[f"payer_amount_{p.user_id}"] = services.format_amount_input(p.paid_cents)
        if expense.split_type == SplitType.EQUAL:
            initial["participants"] = [s.user_id for s in shares]
        for s in shares:
            if expense.split_type == SplitType.EXACT:
                initial[f"exact_{s.user_id}"] = services.format_amount_input(s.owed_cents)
            elif expense.split_type == SplitType.PERCENT and s.input_value is not None:
                initial[f"percent_{s.user_id}"] = format_decimal(s.input_value)
            elif expense.split_type == SplitType.SHARES and s.input_value is not None:
                initial[f"units_{s.user_id}"] = format_decimal(s.input_value)
        if expense.split_type == SplitType.SHARES:
            # Miembros sin partes en este gasto: vacío (no participan).
            share_ids = {s.user_id for s in shares}
            for m in members:
                if m.pk not in share_ids:
                    initial[f"units_{m.pk}"] = ""
        return initial

    def clean_amount(self):
        try:
            return services.parse_amount(self.cleaned_data["amount"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)

    def clean(self):
        cleaned = super().clean()
        payer_mode = cleaned.get("payer_mode")
        split_type = cleaned.get("split_type")

        payer_amounts: dict[int, int] = {}
        payer_errors = False
        if payer_mode == PAYER_MULTIPLE:
            for m in self.members:
                name = f"payer_amount_{m.pk}"
                try:
                    cents = _parse_optional_amount(cleaned.get(name, ""))
                except ValidationError as exc:
                    self.add_error(name, exc.messages)
                    payer_errors = True
                    continue
                if cents is not None:
                    payer_amounts[m.pk] = cents
            if not payer_amounts and not payer_errors:
                self.section_errors["payers"].append("Cargá cuánto pagó cada uno.")
        elif payer_mode == PAYER_SINGLE and cleaned.get("payer") is None:
            self.add_error("payer", "Elegí quién pagó.")

        share_values: dict[int, object] = {}
        share_errors = False
        if split_type == SplitType.EQUAL:
            for uid in cleaned.get("participants") or []:
                share_values[uid] = None
            if not share_values:
                self.section_errors["shares"].append("Elegí al menos un participante.")
        elif split_type in (SplitType.EXACT, SplitType.PERCENT, SplitType.SHARES):
            prefix = {
                SplitType.EXACT: "exact",
                SplitType.PERCENT: "percent",
                SplitType.SHARES: "units",
            }[split_type]
            for m in self.members:
                name = f"{prefix}_{m.pk}"
                raw = cleaned.get(name, "")
                try:
                    if split_type == SplitType.EXACT:
                        value = _parse_optional_amount(raw)
                    else:
                        value = _parse_decimal(raw)
                except ValidationError as exc:
                    self.add_error(name, exc.messages)
                    share_errors = True
                    continue
                if value is not None:
                    share_values[m.pk] = value
            if not share_values and not share_errors:
                self.section_errors["shares"].append("Cargá al menos un participante.")

        self.payer_amounts = payer_amounts
        self.share_values = share_values
        return cleaned

    def is_valid(self) -> bool:
        valid = super().is_valid()
        return valid and not any(self.section_errors.values())

    # Datos para services --------------------------------------------------

    def payer_inputs(self) -> list[services.PayerInput]:
        if self.cleaned_data["payer_mode"] == PAYER_SINGLE:
            return [
                services.PayerInput(
                    user_id=self.cleaned_data["payer"], paid_cents=self.cleaned_data["amount"]
                )
            ]
        return [
            services.PayerInput(user_id=uid, paid_cents=cents)
            for uid, cents in sorted(self.payer_amounts.items())
        ]

    def share_inputs(self) -> list[services.ShareInput]:
        return [
            services.ShareInput(user_id=uid, value=value)
            for uid, value in sorted(self.share_values.items())
        ]

    def service_kwargs(self) -> dict:
        data = self.cleaned_data
        return {
            "description": data["description"],
            "amount_cents": data["amount"],
            "date": data["date"],
            "category": data["category"],
            "split_type": data["split_type"],
            "payers": self.payer_inputs(),
            "shares": self.share_inputs(),
        }

    def add_service_error(self, exc: ValidationError) -> None:
        """Distribuye un ValidationError de services entre campos y secciones."""
        if not hasattr(exc, "error_dict"):
            self.add_error(None, exc.messages)
            return
        field_map = {"amount_cents": "amount"}
        for key, messages in exc.message_dict.items():
            if key in self.section_errors:
                self.section_errors[key].extend(messages)
            elif field_map.get(key, key) in self.fields:
                self.add_error(field_map.get(key, key), messages)
            else:
                self.add_error(None, messages)

    # Presentación ---------------------------------------------------------

    def member_rows(self) -> list[dict]:
        return [
            {
                "user": m,
                "id": m.pk,
                "name": display_name(m),
                "payer_amount": self[f"payer_amount_{m.pk}"],
                "exact": self[f"exact_{m.pk}"],
                "percent": self[f"percent_{m.pk}"],
                "units": self[f"units_{m.pk}"],
                "participant": str(m.pk) in self.participant_values(),
            }
            for m in self.members
        ]

    def participant_values(self) -> list[str]:
        return [str(v) for v in (self["participants"].value() or [])]

    def alpine_state(self) -> dict:
        def val(name):
            value = self[name].value()
            return "" if value is None else str(value)

        return {
            "members": [{"id": str(m.pk), "name": display_name(m)} for m in self.members],
            "amount": val("amount"),
            "payerMode": val("payer_mode") or PAYER_SINGLE,
            "singlePayer": val("payer"),
            "splitType": val("split_type") or SplitType.EQUAL,
            "participants": self.participant_values(),
            "payerAmounts": {str(m.pk): val(f"payer_amount_{m.pk}") for m in self.members},
            "exact": {str(m.pk): val(f"exact_{m.pk}") for m in self.members},
            "percent": {str(m.pk): val(f"percent_{m.pk}") for m in self.members},
            "units": {str(m.pk): val(f"units_{m.pk}") for m in self.members},
        }
