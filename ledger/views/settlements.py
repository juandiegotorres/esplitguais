from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import aliases_for

from .. import services
from ..access import get_group_for_user, get_settlement_for_user
from ..forms_settlements import SettlementForm, display_name


def _positive_int(value: str | None) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _initial_from_query(request, member_ids: set[int]) -> dict:
    initial = {"date": timezone.localdate(), "from_user": request.user.pk}
    from_id = _positive_int(request.GET.get("from"))
    to_id = _positive_int(request.GET.get("to"))
    amount = _positive_int(request.GET.get("amount"))
    if from_id in member_ids:
        initial["from_user"] = from_id
    if to_id in member_ids:
        initial["to_user"] = to_id
    if amount:
        initial["amount"] = services.format_amount_input(amount)
    return initial


@login_required
def settlement_create(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    members = list(group.members.order_by("first_name", "username"))

    if request.method == "POST":
        form = SettlementForm(request.POST, members=members)
        if form.is_valid():
            data = form.cleaned_data
            try:
                settlement = services.create_settlement(
                    group=group,
                    actor=request.user,
                    from_user_id=data["from_user"],
                    to_user_id=data["to_user"],
                    amount_cents=data["amount"],
                    date=data["date"],
                    note=data["note"],
                )
            except ValidationError as exc:
                form.add_service_errors(exc)
            else:
                messages.success(
                    request,
                    f"{display_name(settlement.from_user)} le pagó "
                    f"{services.format_ars(settlement.amount_cents)} "
                    f"a {display_name(settlement.to_user)}",
                )
                return redirect("ledger:balances", group.pk)
    else:
        form = SettlementForm(
            initial=_initial_from_query(request, {u.pk for u in members}), members=members
        )

    return render(
        request,
        "ledger/settlements/settlement_form.html",
        {
            "group": group,
            "active": "saldos",
            "form": form,
            # Claves string: así las lee el JS con el value del <select>.
            "aliases": {str(pk): alias for pk, alias in aliases_for(u.pk for u in members).items()},
        },
    )


@login_required
@require_POST
def settlement_delete(request, group_id: int, settlement_id: int):
    group, settlement = get_settlement_for_user(request.user, group_id, settlement_id)
    services.delete_settlement(settlement, actor=request.user)
    messages.success(
        request,
        f"Se borró el pago de {display_name(settlement.from_user)} a "
        f"{display_name(settlement.to_user)} por {services.format_ars(settlement.amount_cents)}",
    )
    return redirect("ledger:balances", group.pk)
