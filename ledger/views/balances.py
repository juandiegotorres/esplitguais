from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from .. import services
from ..access import get_group_for_user
from ..forms_settlements import display_name


@login_required
def balances(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    members = {u.pk: u for u in group.members.all()}
    balance_by_user = services.group_balances(group)

    rows = [
        {
            "user": user,
            "name": display_name(user),
            "cents": balance_by_user.get(user.pk, 0),
            "abs_cents": abs(balance_by_user.get(user.pk, 0)),
            "is_me": user.pk == request.user.pk,
        }
        for user in members.values()
    ]
    # El usuario actual primero; el resto de mayor acreedor a mayor deudor.
    rows.sort(key=lambda r: (not r["is_me"], -r["cents"], r["name"].lower()))

    create_url = reverse("ledger:settlement_create", args=[group.pk])
    transfers = [
        {
            "from_name": display_name(members[t.from_user_id]),
            "to_name": display_name(members[t.to_user_id]),
            "amount_cents": t.amount_cents,
            "involves_me": request.user.pk in (t.from_user_id, t.to_user_id),
            "url": create_url
            + "?"
            + urlencode({"from": t.from_user_id, "to": t.to_user_id, "amount": t.amount_cents}),
        }
        for t in services.simplify_debts(balance_by_user)
    ]

    settlements = group.settlements.active().select_related("from_user", "to_user")
    return render(
        request,
        "ledger/balances/balances.html",
        {
            "group": group,
            "active": "saldos",
            "rows": rows,
            "transfers": transfers,
            "settlements": settlements,
        },
    )
