from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import redirect, render

from .. import services
from ..access import get_group_for_user, groups_for
from ..forms import AddMemberForm, GroupCreateForm, display_name
from ..models import Expense, ExpensePayer, ExpenseShare, Membership


@login_required
def group_list(request):
    groups = list(groups_for(request.user).order_by("name", "id"))
    rows = [
        {"group": group, "balance": services.group_balances(group).get(request.user.pk, 0)}
        for group in groups
    ]
    return render(request, "ledger/groups/list.html", {"rows": rows})


@login_required
def group_create(request):
    form = GroupCreateForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            group = services.create_group(
                name=form.cleaned_data["name"],
                actor=request.user,
                member_ids=[u.pk for u in form.cleaned_data["members"]],
            )
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Grupo «{group.name}» creado.")
            return redirect("ledger:group_detail", group_id=group.pk)
    return render(request, "ledger/groups/create.html", {"form": form})


@login_required
def group_detail(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    expenses = list(
        Expense.objects.active()
        .filter(group=group)
        .order_by("-date", "-id")
        .prefetch_related(
            Prefetch("payers", queryset=ExpensePayer.objects.select_related("user")),
            Prefetch("shares", queryset=ExpenseShare.objects.all()),
        )
    )
    for expense in expenses:
        payers = list(expense.payers.all())
        if len(payers) == 1:
            expense.payer_label = display_name(payers[0].user)
        else:
            expense.payer_label = f"{len(payers)} personas"
        expense.my_share_cents = sum(
            s.owed_cents for s in expense.shares.all() if s.user_id == request.user.pk
        )
    balance = services.group_balances(group).get(request.user.pk, 0)
    return render(
        request,
        "ledger/groups/detail.html",
        {"group": group, "expenses": expenses, "balance": balance, "active": "gastos"},
    )


@login_required
def group_members(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    form = AddMemberForm(request.POST or None, group=group)
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        try:
            services.add_member(group, user, actor=request.user)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"{display_name(user)} se sumó al grupo.")
            return redirect("ledger:group_members", group_id=group.pk)
    memberships = (
        Membership.objects.filter(group=group).select_related("user").order_by("joined_at", "id")
    )
    return render(
        request,
        "ledger/groups/members.html",
        {
            "group": group,
            "memberships": memberships,
            "form": form,
            "can_add": form.fields["user"].queryset.exists(),
            "active": "miembros",
        },
    )
