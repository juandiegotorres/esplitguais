from django.urls import path

from .views import activity, balances, settlements

urlpatterns = [
    path("grupos/<int:group_id>/saldos/", balances.balances, name="balances"),
    path(
        "grupos/<int:group_id>/liquidaciones/nueva/",
        settlements.settlement_create,
        name="settlement_create",
    ),
    path(
        "grupos/<int:group_id>/liquidaciones/<int:settlement_id>/borrar/",
        settlements.settlement_delete,
        name="settlement_delete",
    ),
    path("grupos/<int:group_id>/actividad/", activity.activity, name="activity"),
]
