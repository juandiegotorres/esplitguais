from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .. import services
from ..access import get_expense_for_user, get_group_for_user
from ..forms import ExpenseForm, display_name, format_decimal
from ..models import Activity, Category

User = get_user_model()


def _members(group):
    return list(User.objects.filter(memberships__group=group).order_by("id"))


def _render_form(request, group, form, expense=None):
    return render(
        request,
        "ledger/expenses/form.html",
        {
            "group": group,
            "form": form,
            "expense": expense,
            "rows": form.member_rows(),
            "alpine_state": form.alpine_state(),
        },
    )


@login_required
def expense_create(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    form = ExpenseForm(request.POST or None, members=_members(group), actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            expense = services.create_expense(
                group=group, actor=request.user, **form.service_kwargs()
            )
        except ValidationError as exc:
            form.add_service_error(exc)
        else:
            messages.success(request, f"Gasto «{expense.description}» guardado.")
            return redirect("ledger:group_detail", group_id=group.pk)
    return _render_form(request, group, form)


@login_required
def expense_edit(request, group_id: int, expense_id: int):
    group, expense = get_expense_for_user(request.user, group_id, expense_id)
    members = _members(group)
    form = ExpenseForm(
        request.POST or None,
        members=members,
        actor=request.user,
        initial=ExpenseForm.initial_from_expense(expense, members),
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.update_expense(expense, actor=request.user, **form.service_kwargs())
        except ValidationError as exc:
            form.add_service_error(exc)
        else:
            messages.success(request, "Gasto actualizado.")
            return redirect("ledger:expense_detail", group_id=group.pk, expense_id=expense.pk)
    return _render_form(request, group, form, expense)


@login_required
def expense_detail(request, group_id: int, expense_id: int):
    group, expense = get_expense_for_user(request.user, group_id, expense_id)
    last_edit = (
        Activity.objects.filter(
            group=group,
            target_type=Activity.TargetType.EXPENSE,
            target_id=expense.pk,
            verb=Activity.Verb.UPDATED,
        )
        .select_related("actor")
        .first()
    )
    shares = list(expense.shares.select_related("user").order_by("user_id"))
    for share in shares:
        share.input_label = (
            format_decimal(share.input_value) if share.input_value is not None else ""
        )
    return render(
        request,
        "ledger/expenses/detail.html",
        {
            "group": group,
            "expense": expense,
            "payers": expense.payers.select_related("user").order_by("user_id"),
            "shares": shares,
            "last_edit": last_edit,
        },
    )


def _percent(part: int, total: int) -> int:
    return round(part * 100 / total) if total else 0


@login_required
def expense_stats(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    spending = services.group_spending(group)
    total = spending.total_cents
    users = User.objects.in_bulk(spending.paid_by_user.keys() | spending.owed_by_user.keys())
    rows = [
        {
            "user": user,
            "name": display_name(user),
            "paid_cents": spending.paid_by_user.get(uid, 0),
            "owed_cents": spending.owed_by_user.get(uid, 0),
            "percent": _percent(spending.paid_by_user.get(uid, 0), total),
            "is_me": uid == request.user.pk,
        }
        for uid, user in users.items()
    ]
    # De quien más puso a quien menos.
    rows.sort(key=lambda r: (-r["paid_cents"], r["name"].lower()))
    top_paid = rows[0]["paid_cents"] if rows else 0
    for row in rows:
        row["is_top"] = top_paid > 0 and row["paid_cents"] == top_paid
    categories = sorted(
        (
            {"label": Category(key).label, "cents": cents, "percent": _percent(cents, total)}
            for key, cents in spending.by_category.items()
        ),
        key=lambda c: (-c["cents"], c["label"]),
    )
    return render(
        request,
        "ledger/expenses/stats.html",
        {
            "group": group,
            "active": "gastos",
            "subtab": "estadisticas",
            "spending": spending,
            "rows": rows,
            "top_names": [r["name"] for r in rows if r["is_top"]],
            "categories": categories,
        },
    )


@login_required
def expense_delete(request, group_id: int, expense_id: int):
    group, expense = get_expense_for_user(request.user, group_id, expense_id)
    if request.method == "POST":
        try:
            services.delete_expense(expense, actor=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, f"Gasto «{expense.description}» borrado.")
        return redirect("ledger:group_detail", group_id=group.pk)
    return render(
        request, "ledger/expenses/confirm_delete.html", {"group": group, "expense": expense}
    )
