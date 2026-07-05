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


def resolve_share_link_by_token(token: str | None) -> ShareLink | None:
    if not token:
        return None
    cleaned = token.strip().lower()
    if not cleaned or len(cleaned) > 24:
        return None
    return ShareLink.objects.filter(token=cleaned).first()


def record_page_view(
    request: HttpRequest,
    *,
    share_link: ShareLink,
    source: str = "direct",
) -> bool:
    if not allow_tracking_request(request):
        return False
    fp = request_fingerprint(request)
    if not should_record_event(
        event_type=ShareEventType.PAGE_VIEW,
        share_link_id=share_link.pk,
        fingerprint=fp,
    ):
        return False
    persist_share_event(
        share_link=share_link,
        event_type=ShareEventType.PAGE_VIEW,
        source=normalize_tracking_source(source),
    )
    return True
