from __future__ import annotations

from django.http import HttpRequest

from analytics.models import ShareEventType, ShareLink
from analytics.services.abuse import (
    allow_tracking_request,
    normalize_tracking_source,
    request_fingerprint,
    should_record_event,
)
from analytics.services.events import persist_share_event


def record_whatsapp_share(
    request: HttpRequest,
    *,
    share_link: ShareLink,
    source: str = "whatsapp",
) -> bool:
    if not allow_tracking_request(request):
        return False
    fp = request_fingerprint(request)
    if not should_record_event(
        event_type=ShareEventType.WHATSAPP_SHARE,
        share_link_id=share_link.pk,
        fingerprint=fp,
    ):
        return False
    persist_share_event(
        share_link=share_link,
        event_type=ShareEventType.WHATSAPP_SHARE,
        source=normalize_tracking_source(source),
    )
    return True


def record_click(
    request: HttpRequest,
    *,
    share_link: ShareLink,
    source: str = "direct",
) -> bool:
    if not allow_tracking_request(request):
        return False
    fp = request_fingerprint(request)
    if not should_record_event(
        event_type=ShareEventType.CLICK,
        share_link_id=share_link.pk,
        fingerprint=fp,
    ):
        return False
    persist_share_event(
        share_link=share_link,
        event_type=ShareEventType.CLICK,
        source=normalize_tracking_source(source),
    )
    return True
