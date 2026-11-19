from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from accounts.models import aliases_for

from .. import services
from ..access import get_group_for_user
from ..forms_settlements import display_name


@login_required
def balances(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    members = {u.pk: u for u in group.members.all()}
    balance_by_user = services.group_balances(group)
    aliases = aliases_for(members)
    me = request.user.pk

    rows = [
        {
            "user": user,
            "name": display_name(user),
            "cents": balance_by_user.get(user.pk, 0),
            "abs_cents": abs(balance_by_user.get(user.pk, 0)),
            "is_me": user.pk == me,
        }
        for user in members.values()
    ]
    # El usuario actual primero; el resto de mayor acreedor a mayor deudor.
    rows.sort(key=lambda r: (not r["is_me"], -r["cents"], r["name"].lower()))

    create_url = reverse("ledger:settlement_create", args=[group.pk])
    # Mis deudas: lo que tengo que pagar (con el alias de a quién) y lo que me tienen que
    # pagar (sin alias). Deudas del grupo: entre otros; solo informativas.
    my_transfers, group_transfers = [], []
    for t in services.simplify_debts(balance_by_user):
        transfer = {
            "from_name": display_name(members[t.from_user_id]),
            "to_name": display_name(members[t.to_user_id]),
            "amount_cents": t.amount_cents,
        }
        if me not in (t.from_user_id, t.to_user_id):
            group_transfers.append(transfer)
            continue
        transfer["i_pay"] = t.from_user_id == me
        if transfer["i_pay"]:
            transfer["to_alias"] = aliases.get(t.to_user_id, "")
        transfer["url"] = (
            create_url
            + "?"
            + urlencode({"from": t.from_user_id, "to": t.to_user_id, "amount": t.amount_cents})
        )
        my_transfers.append(transfer)
    # Primero lo que debés pagar.
    my_transfers.sort(key=lambda t: not t["i_pay"])

    settlements = group.settlements.active().select_related("from_user", "to_user")
    # Si a vos te deben y no cargaste alias, se te sugiere cargarlo.
    suggest_alias = balance_by_user.get(me, 0) > 0 and me not in aliases
    return render(
        request,
        "ledger/balances/balances.html",
        {
            "group": group,
            "active": "saldos",
            "rows": rows,
            "my_transfers": my_transfers,
            "group_transfers": group_transfers,
            "settlements": settlements,
            "suggest_alias": suggest_alias,
        },
    )
