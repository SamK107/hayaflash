from __future__ import annotations

from django.http import HttpRequest

from analytics.models import ShareEvent, ShareEventType
from analytics.services.abuse import (
    allow_conversion_tracking,
    normalize_tracking_source,
)
from analytics.services.events import persist_share_event
from analytics.services.view_tracking import resolve_share_link_by_token


def record_conversion_for_order(
    request: HttpRequest,
    *,
    share_token: str | None,
    order,
    source: str = "direct",
) -> bool:
    if not allow_conversion_tracking(request):
        return False
    link = resolve_share_link_by_token(share_token)
    if link is None:
        return False
    if ShareEvent.objects.filter(
        share_link=link,
        event_type=ShareEventType.CONVERSION,
        order=order,
    ).exists():
        return False
    persist_share_event(
        share_link=link,
        event_type=ShareEventType.CONVERSION,
        source=normalize_tracking_source(source),
        order=order,
    )
    return True
