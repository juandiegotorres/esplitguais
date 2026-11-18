from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from django.utils.timesince import timesince

from ..access import get_group_for_user
from ..forms_settlements import display_name
from ..models import Activity

PAGE_SIZE = 50
RELATIVE_WINDOW = timedelta(days=7)

ICONS = {
    Activity.TargetType.GROUP: "👥",
    Activity.TargetType.MEMBERSHIP: "👤",
    Activity.TargetType.EXPENSE: "🧾",
    Activity.TargetType.SETTLEMENT: "💸",
}


def _when(created_at, now) -> str:
    if now - created_at < timedelta(minutes=1):
        return "recién"
    if now - created_at < RELATIVE_WINDOW:
        return f"hace {timesince(created_at, now, depth=1)}"
    return timezone.localtime(created_at).strftime("%d/%m/%Y %H:%M")


@login_required
def activity(request, group_id: int):
    group = get_group_for_user(request.user, group_id)
    page = Paginator(group.activities.select_related("actor"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    now = timezone.now()
    entries = [
        {
            "actor": display_name(a.actor),
            "summary": a.payload.get("summary", ""),
            "icon": ICONS.get(a.target_type, "•"),
            "type_label": a.get_target_type_display(),
            "is_deleted": a.verb == Activity.Verb.DELETED,
            "created_at": a.created_at,
            "when": _when(a.created_at, now),
        }
        for a in page.object_list
    ]
    return render(
        request,
        "ledger/activity/activity.html",
        {"group": group, "active": "actividad", "page": page, "entries": entries},
    )
