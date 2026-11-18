from django.shortcuts import get_object_or_404

from .models import Expense, Group, Settlement


def groups_for(user):
    """Grupos visibles para el usuario: solo aquellos de los que es miembro."""
    return Group.objects.filter(memberships__user=user)


def get_group_for_user(user, group_id: int) -> Group:
    """404 si el grupo no existe o el usuario no es miembro (no se filtra existencia)."""
    return get_object_or_404(groups_for(user), pk=group_id)


def get_expense_for_user(user, group_id: int, expense_id: int) -> tuple[Group, Expense]:
    group = get_group_for_user(user, group_id)
    expense = get_object_or_404(Expense.objects.active(), pk=expense_id, group=group)
    return group, expense


def get_settlement_for_user(user, group_id: int, settlement_id: int) -> tuple[Group, Settlement]:
    group = get_group_for_user(user, group_id)
    settlement = get_object_or_404(Settlement.objects.active(), pk=settlement_id, group=group)
    return group, settlement
