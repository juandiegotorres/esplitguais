from .urls_balances import urlpatterns as balances_urlpatterns
from .urls_groups import urlpatterns as groups_urlpatterns

app_name = "ledger"

urlpatterns = groups_urlpatterns + balances_urlpatterns
