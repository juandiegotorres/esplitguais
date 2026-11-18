from django.urls import path

from .views import expenses, groups

urlpatterns = [
    path("", groups.group_list, name="group_list"),
    path("grupos/nuevo/", groups.group_create, name="group_create"),
    path("grupos/<int:group_id>/", groups.group_detail, name="group_detail"),
    path("grupos/<int:group_id>/miembros/", groups.group_members, name="group_members"),
    path("grupos/<int:group_id>/gastos/nuevo/", expenses.expense_create, name="expense_create"),
    path(
        "grupos/<int:group_id>/gastos/<int:expense_id>/",
        expenses.expense_detail,
        name="expense_detail",
    ),
    path(
        "grupos/<int:group_id>/gastos/<int:expense_id>/editar/",
        expenses.expense_edit,
        name="expense_edit",
    ),
    path(
        "grupos/<int:group_id>/gastos/<int:expense_id>/borrar/",
        expenses.expense_delete,
        name="expense_delete",
    ),
]
