from django.db.models import Q
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
    """404 salvo para las partes del pago (quien pagó o recibió) o quien lo registró."""
    group = get_group_for_user(user, group_id)
    settlement = get_object_or_404(
        Settlement.objects.active().filter(
            Q(from_user=user) | Q(to_user=user) | Q(created_by=user)
        ),
        pk=settlement_id,
        group=group,
    )
    return group, settlement
