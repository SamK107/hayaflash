from __future__ import annotations

import hashlib
import re

from django.core.cache import cache
from django.http import HttpRequest

_BOT_UA = re.compile(
    r"(bot|crawl|spider|slurp|curl|wget|python-requests|scrapy|headless)",
    re.I,
)
_VALID_SOURCE = re.compile(r"^[a-z0-9_-]{1,32}$")

IP_RATE_WINDOW = 60
IP_RATE_MAX = 60
FP_RATE_WINDOW = 60
FP_RATE_MAX = 30
DEDUPE_SECONDS = 45


def normalize_tracking_source(raw: str | None) -> str:
    if not raw:
        return "direct"
    value = raw.strip().lower()[:32]
    if not value or not _VALID_SOURCE.match(value):
        return "direct"
    return value


def client_ip(request: HttpRequest) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]


def request_fingerprint(request: HttpRequest) -> str:
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:256]
    raw = f"{client_ip(request)}|{ua}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def is_suspected_bot(request: HttpRequest) -> bool:
    ua = request.META.get("HTTP_USER_AGENT") or ""
    if not ua.strip():
        return False
    return bool(_BOT_UA.search(ua))


def allow_tracking_request(request: HttpRequest) -> bool:
    if is_suspected_bot(request):
        return False
    ip_key = f"viral:track:ip:{client_ip(request)}"
    try:
        n = cache.incr(ip_key)
    except ValueError:
        cache.set(ip_key, 1, IP_RATE_WINDOW)
        n = 1
    if n > IP_RATE_MAX:
        return False

    fp_key = f"viral:track:fp:{request_fingerprint(request)}"
    try:
        m = cache.incr(fp_key)
    except ValueError:
        cache.set(fp_key, 1, FP_RATE_WINDOW)
        m = 1
    return m <= FP_RATE_MAX


def allow_conversion_tracking(request: HttpRequest) -> bool:
    """Conversions are server-validated; IP throttle only (no bot heuristic)."""
    ip_key = f"viral:track:conv:ip:{client_ip(request)}"
    try:
        n = cache.incr(ip_key)
    except ValueError:
        cache.set(ip_key, 1, IP_RATE_WINDOW)
        n = 1
    return n <= IP_RATE_MAX * 3


def should_record_event(
    *,
    event_type: str,
    share_link_id: int,
    fingerprint: str,
) -> bool:
    """Per-link dedupe window to reduce spam click inflation."""
    dedupe_key = f"viral:dedupe:{event_type}:{share_link_id}:{fingerprint}"
    if cache.get(dedupe_key):
        return False
    cache.set(dedupe_key, 1, DEDUPE_SECONDS)
    return True
