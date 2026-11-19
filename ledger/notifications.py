"""Qué se notifica y a quién. El envío lo hace pwa.push.

Gastos (nuevos y editados): a quienes participan, es decir pagaron o tienen parte, salvo
quien lo cargó. Al editar también a quienes participaban antes, para que se enteren de
que salieron. Pagos registrados: a la otra parte del pago.
"""

from django.urls import reverse

from pwa import push

from .forms import display_name
from .models import Expense, Settlement
from .services import format_ars


def participant_ids(expense: Expense) -> set[int]:
    paid = expense.payers.filter(paid_cents__gt=0).values_list("user_id", flat=True)
    owed = expense.shares.filter(owed_cents__gt=0).values_list("user_id", flat=True)
    return set(paid) | set(owed)


def _your_part(paid: int, owed: int) -> str:
    if not paid and not owed:
        return "Ya no participás."
    net = paid - owed
    if net > 0:
        return f"Te deben {format_ars(net)}."
    if net < 0:
        return f"Debés {format_ars(-net)}."
    return "Pagaste tu parte."


def expense_saved(expense: Expense, *, actor, created: bool, previous_ids=frozenset()) -> None:
    if not push.enabled():
        return
    paid = dict(expense.payers.values_list("user_id", "paid_cents"))
    owed = dict(expense.shares.values_list("user_id", "owed_cents"))
    recipients = (participant_ids(expense) | set(previous_ids)) - {actor.pk}
    if not recipients:
        return
    verb = "cargó" if created else "editó"
    headline = (
        f"{display_name(actor)} {verb} «{expense.description}» por "
        f"{format_ars(expense.amount_cents)}."
    )
    url = reverse("ledger:expense_detail", args=[expense.group_id, expense.pk])
    push.send(
        {
            uid: push.Notification(
                title=expense.group.name,
                body=f"{headline} {_your_part(paid.get(uid, 0), owed.get(uid, 0))}",
                url=url,
                tag=f"expense-{expense.pk}",
            )
            for uid in recipients
        }
    )


def settlement_created(settlement: Settlement, *, actor) -> None:
    if not push.enabled():
        return
    amount = format_ars(settlement.amount_cents)
    if actor.pk == settlement.from_user_id:
        recipient, what = settlement.to_user_id, f"te pagó {amount}"
    else:
        recipient, what = settlement.from_user_id, f"le pagaste {amount}"
    push.send(
        {
            recipient: push.Notification(
                title=settlement.group.name,
                body=f"{display_name(actor)} registró que {what}.",
                url=reverse("ledger:balances", args=[settlement.group_id]),
                tag=f"settlement-{settlement.pk}",
            )
        }
    )
