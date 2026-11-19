"""Lógica de dinero del ledger: importes, repartos, saldos y simplificación de deudas.

Todos los importes son centavos enteros (``int``). Las escrituras son atómicas,
validan los invariantes del gasto/liquidación y registran ``Activity``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .models import (
    Activity,
    Category,
    Expense,
    ExpensePayer,
    ExpenseShare,
    Group,
    Membership,
    Settlement,
    SplitType,
)

# Límite de BigIntegerField; evita desbordes al guardar.
MAX_CENTS = 9_223_372_036_854_775_807
# ExpenseShare.input_value tiene decimal_places=4.
_WEIGHT_SCALE = 10_000
_MAX_INPUT_VALUE = Decimal("99999999.9999")  # max_digits=12, decimal_places=4


@dataclass(frozen=True)
class PayerInput:
    user_id: int
    paid_cents: int


@dataclass(frozen=True)
class ShareInput:
    user_id: int
    value: Decimal | int | None = None


@dataclass(frozen=True)
class Transfer:
    from_user_id: int
    to_user_id: int
    amount_cents: int


@dataclass(frozen=True)
class GroupSpending:
    total_cents: int
    expense_count: int
    paid_by_user: dict[int, int]
    owed_by_user: dict[int, int]
    by_category: dict[str, int]


# ---------------------------------------------------------------------------
# Formato y parseo de importes
# ---------------------------------------------------------------------------

_DIGITS = re.compile(r"\d+")
_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")
_DOT_DECIMAL = re.compile(r"(\d+)\.(\d{1,2})")


def parse_amount(text: str) -> int:
    """Convierte un importe escrito en formato argentino a centavos.

    Acepta ``15000``, ``15.000``, ``15.000,50``, ``15000,5`` y ``$ 1.234,56``.
    Sin coma, un único punto seguido de 1 o 2 dígitos se toma como decimal
    (``15.5`` → 1550), como lo escriben los teclados numéricos en inglés.
    """
    error = ValidationError(
        "Ingresá un importe válido, por ejemplo 15.000 o 15.000,50.", code="invalid"
    )
    if text is None:
        raise ValidationError("Ingresá un importe.", code="required")
    cleaned = re.sub(r"\s", "", str(text)).replace("$", "")
    if not cleaned:
        raise ValidationError("Ingresá un importe.", code="required")
    if cleaned.startswith("-"):
        raise ValidationError("El importe tiene que ser mayor a cero.", code="min_value")

    if "," in cleaned:
        integer, _, fraction = cleaned.partition(",")
        if not _DIGITS.fullmatch(fraction or "x"):
            raise error
        if len(fraction) > 2:
            raise ValidationError(
                "El importe admite como máximo 2 decimales.", code="max_decimal_places"
            )
        if _THOUSANDS.fullmatch(integer):
            integer = integer.replace(".", "")
        elif not _DIGITS.fullmatch(integer):
            raise error
    elif "." in cleaned:
        if _THOUSANDS.fullmatch(cleaned):
            integer, fraction = cleaned.replace(".", ""), ""
        elif match := _DOT_DECIMAL.fullmatch(cleaned):
            integer, fraction = match.groups()
        else:
            raise error
    elif _DIGITS.fullmatch(cleaned):
        integer, fraction = cleaned, ""
    else:
        raise error

    cents = int(integer) * 100 + int(fraction.ljust(2, "0"))
    if cents <= 0:
        raise ValidationError("El importe tiene que ser mayor a cero.", code="min_value")
    if cents > MAX_CENTS:
        raise ValidationError("El importe es demasiado grande.", code="max_value")
    return cents


def _group_thousands(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def format_amount_input(cents: int) -> str:
    """1500050 → ``"15.000,50"`` (sin signo pesos, para prellenar formularios)."""
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    pesos, rest = divmod(abs(cents), 100)
    return f"{sign}{_group_thousands(pesos)},{rest:02d}"


def format_ars(cents: int) -> str:
    """123456789 → ``"$ 1.234.567,89"``; -5000 → ``"-$ 50,00"``."""
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    return f"{sign}$ {format_amount_input(abs(cents))}"


# ---------------------------------------------------------------------------
# Repartos
# ---------------------------------------------------------------------------


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_amount(amount_cents) -> None:
    if not _is_int(amount_cents) or amount_cents <= 0:
        raise ValidationError(
            {"amount_cents": ["El importe tiene que ser mayor a cero."]}
        )
    if amount_cents > MAX_CENTS:
        raise ValidationError({"amount_cents": ["El importe es demasiado grande."]})


def _share_error(message: str) -> ValidationError:
    return ValidationError({"shares": [message]})


def _to_decimal(value) -> Decimal:
    """Convierte un porcentaje o cantidad de partes a Decimal con ≤ 4 decimales."""
    if isinstance(value, Decimal):
        number = value
    elif _is_int(value):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip().replace(",", "."))
        except InvalidOperation:
            raise _share_error("Ingresá un número válido para cada participante.") from None
    else:
        raise _share_error("Ingresá un número válido para cada participante.")
    if not number.is_finite():
        raise _share_error("Ingresá un número válido para cada participante.")
    if number != number.quantize(Decimal(1).scaleb(-4)):
        raise _share_error("Se admiten como máximo 4 decimales.")
    if abs(number) > _MAX_INPUT_VALUE:
        raise _share_error("El valor es demasiado grande.")
    return number


def _distribute(amount_cents: int, weights: dict[int, int]) -> dict[int, int]:
    """Reparte proporcionalmente a pesos enteros: floor por persona y los centavos
    sobrantes, de a uno, a los primeros participantes con peso > 0 ordenados por id."""
    total_weight = sum(weights.values())
    result = {uid: amount_cents * w // total_weight for uid, w in weights.items()}
    remainder = amount_cents - sum(result.values())
    for uid in sorted(uid for uid, w in weights.items() if w > 0)[:remainder]:
        result[uid] += 1
    return dict(sorted(result.items()))


def compute_shares(
    amount_cents: int, split_type: str, shares: Sequence[ShareInput]
) -> dict[int, int]:
    """Devuelve ``user_id → owed_cents`` (Σ = ``amount_cents``)."""
    _validate_amount(amount_cents)
    if not shares:
        raise _share_error("Elegí al menos un participante.")
    user_ids = [s.user_id for s in shares]
    if len(set(user_ids)) != len(user_ids):
        raise _share_error("Hay participantes repetidos.")

    if split_type == SplitType.EQUAL:
        return _distribute(amount_cents, {uid: 1 for uid in user_ids})

    if split_type == SplitType.EXACT:
        result = {}
        for share in shares:
            if not _is_int(share.value) or share.value < 0:
                raise _share_error("Cada importe tiene que ser un número de centavos ≥ 0.")
            result[share.user_id] = share.value
        total = sum(result.values())
        if total != amount_cents:
            raise _share_error(
                f"Los importes suman {format_ars(total)} y el gasto es de "
                f"{format_ars(amount_cents)}."
            )
        return dict(sorted(result.items()))

    if split_type == SplitType.PERCENT:
        values = {s.user_id: _to_decimal(s.value) for s in shares}
        if any(v < 0 for v in values.values()):
            raise _share_error("Los porcentajes no pueden ser negativos.")
        total = sum(values.values(), Decimal(0))
        if total != 100:
            raise _share_error(
                f"Los porcentajes suman {total.normalize():f} % y tienen que sumar 100 %."
            )
        return _distribute(
            amount_cents, {uid: int(v * _WEIGHT_SCALE) for uid, v in values.items()}
        )

    if split_type == SplitType.SHARES:
        values = {s.user_id: _to_decimal(s.value) for s in shares}
        if any(v <= 0 for v in values.values()):
            raise _share_error("Cada participante tiene que tener más de 0 partes.")
        return _distribute(
            amount_cents, {uid: int(v * _WEIGHT_SCALE) for uid, v in values.items()}
        )

    raise ValidationError({"split_type": ["Tipo de reparto inválido."]})


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _display_name(user) -> str:
    return user.get_full_name() or user.get_username()


def _format_date(value) -> str:
    return value.strftime("%d/%m/%Y")


def _log(group, actor, verb, target_type, target_id, summary, **extra) -> Activity:
    return Activity.objects.create(
        group=group,
        actor=actor,
        verb=verb,
        target_type=target_type,
        target_id=target_id,
        payload={"summary": summary, **extra},
    )


def _member_ids(group) -> set[int]:
    return set(Membership.objects.filter(group=group).values_list("user_id", flat=True))


def _validated_expense_rows(
    *, group, description, amount_cents, date, category, split_type, payers, shares
):
    """Valida todo el gasto y devuelve (descripción limpia, pagos, deudas, input_values)."""
    errors: dict[str, list[str]] = {}

    description = (description or "").strip()
    if not description:
        errors.setdefault("description", []).append("Ingresá una descripción.")
    elif len(description) > Expense._meta.get_field("description").max_length:
        errors.setdefault("description", []).append("La descripción es demasiado larga.")
    if not isinstance(date, date_type):
        errors.setdefault("date", []).append("Ingresá una fecha válida.")
    if category not in Category.values:
        errors.setdefault("category", []).append("Categoría inválida.")
    if split_type not in SplitType.values:
        errors.setdefault("split_type", []).append("Tipo de reparto inválido.")

    try:
        _validate_amount(amount_cents)
    except ValidationError as exc:
        errors.update(exc.message_dict)
        raise ValidationError(errors) from None

    members = _member_ids(group)

    payer_errors = []
    paid: dict[int, int] = {}
    if not payers:
        payer_errors.append("Indicá quién pagó.")
    for payer in payers:
        if payer.user_id in paid:
            payer_errors.append("Hay pagadores repetidos.")
        elif payer.user_id not in members:
            payer_errors.append("Todos los pagadores tienen que ser miembros del grupo.")
        elif not _is_int(payer.paid_cents) or payer.paid_cents <= 0:
            payer_errors.append("Cada pagador tiene que haber pagado más de $ 0.")
        paid[payer.user_id] = payer.paid_cents
    if not payer_errors and sum(paid.values()) != amount_cents:
        payer_errors.append(
            f"Los pagos suman {format_ars(sum(paid.values()))} y el gasto es de "
            f"{format_ars(amount_cents)}."
        )
    if payer_errors:
        errors["payers"] = list(dict.fromkeys(payer_errors))

    owed: dict[int, int] = {}
    input_values: dict[int, Decimal | None] = {}
    if any(s.user_id not in members for s in shares):
        errors.setdefault("shares", []).append(
            "Todos los participantes tienen que ser miembros del grupo."
        )
    elif "split_type" not in errors:
        try:
            owed = compute_shares(amount_cents, split_type, shares)
        except ValidationError as exc:
            for field, messages in exc.message_dict.items():
                errors.setdefault(field, []).extend(messages)
        else:
            for share in shares:
                input_values[share.user_id] = (
                    _to_decimal(share.value)
                    if split_type in (SplitType.PERCENT, SplitType.SHARES)
                    else None
                )

    if errors:
        raise ValidationError(errors)
    return description, paid, owed, input_values


def _write_rows(expense, paid, owed, input_values) -> None:
    ExpensePayer.objects.bulk_create(
        ExpensePayer(expense=expense, user_id=uid, paid_cents=cents)
        for uid, cents in sorted(paid.items())
    )
    ExpenseShare.objects.bulk_create(
        ExpenseShare(
            expense=expense, user_id=uid, owed_cents=cents, input_value=input_values[uid]
        )
        for uid, cents in owed.items()
    )


# ---------------------------------------------------------------------------
# Grupos y miembros
# ---------------------------------------------------------------------------


def create_group(*, name: str, actor, member_ids: Iterable[int]) -> Group:
    name = (name or "").strip()
    if not name:
        raise ValidationError({"name": ["Ingresá un nombre para el grupo."]})
    if len(name) > Group._meta.get_field("name").max_length:
        raise ValidationError({"name": ["El nombre es demasiado largo."]})
    ids = set(member_ids) | {actor.pk}
    users = list(get_user_model().objects.filter(pk__in=ids).order_by("pk"))
    if len(users) != len(ids):
        raise ValidationError({"member_ids": ["Alguno de los miembros no existe."]})

    with transaction.atomic():
        group = Group.objects.create(name=name, created_by=actor)
        Membership.objects.bulk_create(Membership(group=group, user=u) for u in users)
        _log(
            group,
            actor,
            Activity.Verb.CREATED,
            Activity.TargetType.GROUP,
            group.pk,
            f"creó el grupo «{name}»",
            members=[u.pk for u in users],
        )
    return group


def add_member(group, user, *, actor) -> Membership:
    with transaction.atomic():
        if Membership.objects.filter(group=group, user=user).exists():
            raise ValidationError(
                {"user": [f"{_display_name(user)} ya es miembro del grupo."]}
            )
        membership = Membership.objects.create(group=group, user=user)
        _log(
            group,
            actor,
            Activity.Verb.CREATED,
            Activity.TargetType.MEMBERSHIP,
            membership.pk,
            f"agregó a {_display_name(user)} al grupo",
            user_id=user.pk,
        )
    return membership


# ---------------------------------------------------------------------------
# Gastos
# ---------------------------------------------------------------------------


def create_expense(
    *,
    group,
    actor,
    description,
    amount_cents,
    date,
    category,
    split_type,
    payers: Sequence[PayerInput],
    shares: Sequence[ShareInput],
) -> Expense:
    with transaction.atomic():
        description, paid, owed, input_values = _validated_expense_rows(
            group=group,
            description=description,
            amount_cents=amount_cents,
            date=date,
            category=category,
            split_type=split_type,
            payers=payers,
            shares=shares,
        )
        expense = Expense.objects.create(
            group=group,
            description=description,
            amount_cents=amount_cents,
            date=date,
            category=category,
            split_type=split_type,
            created_by=actor,
        )
        _write_rows(expense, paid, owed, input_values)
        _log(
            group,
            actor,
            Activity.Verb.CREATED,
            Activity.TargetType.EXPENSE,
            expense.pk,
            f"creó el gasto «{description}» por {format_ars(amount_cents)}",
            amount_cents=amount_cents,
        )
    return expense


def update_expense(
    expense,
    *,
    actor,
    description,
    amount_cents,
    date,
    category,
    split_type,
    payers: Sequence[PayerInput],
    shares: Sequence[ShareInput],
) -> Expense:
    with transaction.atomic():
        current = Expense.objects.select_for_update().get(pk=expense.pk)
        if current.deleted_at is not None:
            raise ValidationError("No se puede editar un gasto borrado.", code="deleted")
        description, paid, owed, input_values = _validated_expense_rows(
            group=current.group,
            description=description,
            amount_cents=amount_cents,
            date=date,
            category=category,
            split_type=split_type,
            payers=payers,
            shares=shares,
        )

        old_paid = dict(current.payers.values_list("user_id", "paid_cents"))
        old_shares = {
            uid: (cents, value)
            for uid, cents, value in current.shares.values_list(
                "user_id", "owed_cents", "input_value"
            )
        }
        new_shares = {uid: (owed[uid], input_values[uid]) for uid in owed}

        changes: list[str] = []
        details: list[str] = []
        if current.description != description:
            changes.append("description")
            details.append(f"descripción («{current.description}» → «{description}»)")
        if current.amount_cents != amount_cents:
            changes.append("amount_cents")
            details.append(
                f"importe ({format_ars(current.amount_cents)} → {format_ars(amount_cents)})"
            )
        if current.date != date:
            changes.append("date")
            details.append(f"fecha ({_format_date(current.date)} → {_format_date(date)})")
        if current.category != category:
            changes.append("category")
            details.append(
                f"categoría ({Category(current.category).label} → {Category(category).label})"
            )
        if current.split_type != split_type:
            changes.append("split_type")
            details.append(
                f"tipo de reparto ({SplitType(current.split_type).label} → "
                f"{SplitType(split_type).label})"
            )
        elif old_shares != new_shares:
            changes.append("shares")
            details.append("reparto")
        if old_paid != paid:
            changes.append("payers")
            details.append("pagadores")

        current.description = description
        current.amount_cents = amount_cents
        current.date = date
        current.category = category
        current.split_type = split_type
        current.save()
        current.payers.all().delete()
        current.shares.all().delete()
        _write_rows(current, paid, owed, input_values)

        if details:
            summary = f"editó el gasto «{description}»: cambió {', '.join(details)}"
        else:
            summary = f"editó el gasto «{description}» sin cambios"
        _log(
            current.group,
            actor,
            Activity.Verb.UPDATED,
            Activity.TargetType.EXPENSE,
            current.pk,
            summary,
            changes=changes,
        )
    return current


def delete_expense(expense, *, actor) -> None:
    with transaction.atomic():
        current = Expense.objects.select_for_update().get(pk=expense.pk)
        if current.deleted_at is not None:
            raise ValidationError("El gasto ya estaba borrado.", code="deleted")
        current.deleted_at = timezone.now()
        current.save(update_fields=["deleted_at", "updated_at"])
        expense.deleted_at = current.deleted_at
        _log(
            current.group,
            actor,
            Activity.Verb.DELETED,
            Activity.TargetType.EXPENSE,
            current.pk,
            f"borró el gasto «{current.description}» por {format_ars(current.amount_cents)}",
            amount_cents=current.amount_cents,
        )


# ---------------------------------------------------------------------------
# Liquidaciones
# ---------------------------------------------------------------------------


def create_settlement(
    *, group, actor, from_user_id, to_user_id, amount_cents, date, note=""
) -> Settlement:
    errors: dict[str, list[str]] = {}
    try:
        _validate_amount(amount_cents)
    except ValidationError as exc:
        errors.update(exc.message_dict)
    if not isinstance(date, date_type):
        errors["date"] = ["Ingresá una fecha válida."]
    note = (note or "").strip()
    if len(note) > Settlement._meta.get_field("note").max_length:
        errors["note"] = ["La nota es demasiado larga."]

    with transaction.atomic():
        members = {
            m.user_id: m.user
            for m in Membership.objects.filter(
                group=group, user_id__in=[from_user_id, to_user_id]
            ).select_related("user")
        }
        if from_user_id not in members:
            errors["from_user_id"] = ["Quien paga tiene que ser miembro del grupo."]
        if to_user_id not in members:
            errors["to_user_id"] = ["Quien recibe tiene que ser miembro del grupo."]
        if from_user_id == to_user_id:
            errors["to_user_id"] = ["Quien paga y quien recibe tienen que ser distintos."]
        # Solo las partes registran el pago: quien lo hizo o quien lo recibió.
        if actor.pk not in (from_user_id, to_user_id):
            errors[NON_FIELD_ERRORS] = ["Solo podés registrar pagos que hiciste o que recibiste."]
        if errors:
            raise ValidationError(errors)

        settlement = Settlement.objects.create(
            group=group,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount_cents=amount_cents,
            date=date,
            note=note,
            created_by=actor,
        )
        _log(
            group,
            actor,
            Activity.Verb.CREATED,
            Activity.TargetType.SETTLEMENT,
            settlement.pk,
            f"registró que {_display_name(members[from_user_id])} le pagó "
            f"{format_ars(amount_cents)} a {_display_name(members[to_user_id])}",
            amount_cents=amount_cents,
        )
    return settlement


def delete_settlement(settlement, *, actor) -> None:
    with transaction.atomic():
        current = (
            Settlement.objects.select_for_update()
            .select_related("from_user", "to_user")
            .get(pk=settlement.pk)
        )
        if current.deleted_at is not None:
            raise ValidationError("La liquidación ya estaba borrada.", code="deleted")
        current.deleted_at = timezone.now()
        current.save(update_fields=["deleted_at"])
        settlement.deleted_at = current.deleted_at
        _log(
            current.group,
            actor,
            Activity.Verb.DELETED,
            Activity.TargetType.SETTLEMENT,
            current.pk,
            f"borró el pago de {_display_name(current.from_user)} a "
            f"{_display_name(current.to_user)} por {format_ars(current.amount_cents)}",
            amount_cents=current.amount_cents,
        )


# ---------------------------------------------------------------------------
# Saldos
# ---------------------------------------------------------------------------


def group_balances(group) -> dict[int, int]:
    """``user_id → centavos`` para todos los miembros; positivo = le deben."""
    balances = {uid: 0 for uid in _member_ids(group)}

    def add(rows, sign):
        for uid, total in rows:
            balances[uid] = balances.get(uid, 0) + sign * (total or 0)

    active_expense = {"expense__group": group, "expense__deleted_at__isnull": True}
    add(
        ExpensePayer.objects.filter(**active_expense)
        .values("user_id")
        .annotate(total=Sum("paid_cents"))
        .values_list("user_id", "total"),
        1,
    )
    add(
        ExpenseShare.objects.filter(**active_expense)
        .values("user_id")
        .annotate(total=Sum("owed_cents"))
        .values_list("user_id", "total"),
        -1,
    )
    settlements = Settlement.objects.active().filter(group=group)
    add(
        settlements.values("from_user_id")
        .annotate(total=Sum("amount_cents"))
        .values_list("from_user_id", "total"),
        1,
    )
    add(
        settlements.values("to_user_id")
        .annotate(total=Sum("amount_cents"))
        .values_list("to_user_id", "total"),
        -1,
    )
    return dict(sorted(balances.items()))


def group_spending(group) -> GroupSpending:
    """Totales de los gastos activos del grupo (las liquidaciones no son gasto).

    ``paid_by_user``: cuánto puso cada uno; ``owed_by_user``: cuánto le tocaba según los
    repartos. Incluyen a todos los miembros (0 si no participó). ``by_category`` solo
    lleva categorías con gastos.
    """
    expenses = Expense.objects.active().filter(group=group)
    totals = expenses.aggregate(total=Sum("amount_cents"), count=Count("id"))
    by_category = dict(
        expenses.order_by()
        .values("category")
        .annotate(total=Sum("amount_cents"))
        .values_list("category", "total")
    )

    active_expense = {"expense__group": group, "expense__deleted_at__isnull": True}
    members = _member_ids(group)
    paid = dict.fromkeys(members, 0)
    paid.update(
        ExpensePayer.objects.filter(**active_expense)
        .values("user_id")
        .annotate(total=Sum("paid_cents"))
        .values_list("user_id", "total")
    )
    owed = dict.fromkeys(members, 0)
    owed.update(
        ExpenseShare.objects.filter(**active_expense)
        .values("user_id")
        .annotate(total=Sum("owed_cents"))
        .values_list("user_id", "total")
    )
    return GroupSpending(
        total_cents=totals["total"] or 0,
        expense_count=totals["count"],
        paid_by_user=dict(sorted(paid.items())),
        owed_by_user=dict(sorted(owed.items())),
        by_category=by_category,
    )


def simplify_debts(balances: Mapping[int, int]) -> list[Transfer]:
    """Empareja voraz al mayor deudor con el mayor acreedor (empates: menor user_id).

    Cada transferencia salda al menos a uno de los dos, así que hay como máximo
    n − 1 transferencias entre los n usuarios con saldo distinto de 0.
    """
    if sum(balances.values()) != 0:
        raise ValueError("Los saldos no suman 0.")
    creditors = {uid: amount for uid, amount in balances.items() if amount > 0}
    debtors = {uid: -amount for uid, amount in balances.items() if amount < 0}
    transfers: list[Transfer] = []
    while creditors and debtors:
        creditor = min(creditors, key=lambda uid: (-creditors[uid], uid))
        debtor = min(debtors, key=lambda uid: (-debtors[uid], uid))
        amount = min(creditors[creditor], debtors[debtor])
        transfers.append(Transfer(debtor, creditor, amount))
        creditors[creditor] -= amount
        debtors[debtor] -= amount
        if creditors[creditor] == 0:
            del creditors[creditor]
        if debtors[debtor] == 0:
            del debtors[debtor]
    return transfers
