"""Backward-compatible tracking re-exports."""

from analytics.services.abuse import normalize_tracking_source
from analytics.services.conversion_tracking import record_conversion_for_order
from analytics.services.share_tracking import record_click, record_whatsapp_share
from analytics.services.view_tracking import (
    record_page_view,
    resolve_share_link_by_token,
)


def record_share_event(request, *, share_link, event_type, source="direct", order=None):
    """Legacy dispatcher — prefer specific tracking modules."""
    from analytics.models import ShareEventType as ET

    if event_type == ET.WHATSAPP_SHARE:
        return record_whatsapp_share(request, share_link=share_link, source=source)
    if event_type == ET.CLICK:
        return record_click(request, share_link=share_link, source=source)
    if event_type == ET.PAGE_VIEW:
        return record_page_view(request, share_link=share_link, source=source)
    if event_type == ET.CONVERSION:
        return record_conversion_for_order(
            request,
            share_token=share_link.token,
            order=order,
            source=source,
        )
    return False


__all__ = [
    "normalize_tracking_source",
    "record_conversion_for_order",
    "record_page_view",
    "record_share_event",
    "resolve_share_link_by_token",
]
