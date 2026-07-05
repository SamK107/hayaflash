from __future__ import annotations

from django.db import transaction
from django.db.models import F

from analytics.models import ShareEvent, ShareEventType, ShareLink


def persist_share_event(
    *,
    share_link: ShareLink,
    event_type: str,
    source: str,
    order=None,
) -> None:
    updates: dict[str, F] = {}
    if event_type in (ShareEventType.PAGE_VIEW, ShareEventType.CLICK):
        updates["click_count"] = F("click_count") + 1
    elif event_type == ShareEventType.WHATSAPP_SHARE:
        updates["share_count"] = F("share_count") + 1
    elif event_type == ShareEventType.CONVERSION:
        updates["conversion_count"] = F("conversion_count") + 1

    with transaction.atomic():
        ShareEvent.objects.create(
            share_link=share_link,
            event_type=event_type,
            source=source,
            order=order,
        )
        if updates:
            ShareLink.objects.filter(pk=share_link.pk).update(**updates)
