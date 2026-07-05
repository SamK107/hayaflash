from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

DEFAULT_STATS_TTL = 300
DEFAULT_PAGE_VERSION_TTL = 86400


def _stats_ttl() -> int:
    return int(getattr(settings, "VIRAL_STATS_CACHE_SECONDS", DEFAULT_STATS_TTL))


def _version_ttl() -> int:
    val = int(getattr(settings, "VIRAL_PAGE_VERSION_TTL_SECONDS", DEFAULT_PAGE_VERSION_TTL))
    return max(val, 1)  # TTL=0 means "don't cache" in Django — always store at least 1s


def seller_stats_key(seller_id: int) -> str:
    return f"viral:stats:seller:{seller_id}"


def seller_page_version_key(slug: str) -> str:
    return f"viral:ver:seller:{slug}"


def flash_page_version_key(slug: str) -> str:
    return f"viral:ver:flash:{slug}"


def bump_page_version(key: str) -> None:
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, _version_ttl())


def get_page_version(key: str) -> int:
    val = cache.get(key)
    return int(val) if val is not None else 0


def invalidate_seller_public_cache(*, seller_id: int, seller_slug: str) -> None:
    cache.delete(seller_stats_key(seller_id))
    bump_page_version(seller_page_version_key(seller_slug))


def invalidate_flash_sale_public_cache(*, flash_slug: str, seller_id: int, seller_slug: str) -> None:
    bump_page_version(flash_page_version_key(flash_slug))
    invalidate_seller_public_cache(seller_id=seller_id, seller_slug=seller_slug)


def invalidate_for_order(*, flash_sale_id: int, seller_id: int, seller_slug: str, flash_slug: str) -> None:
    invalidate_flash_sale_public_cache(
        flash_slug=flash_slug,
        seller_id=seller_id,
        seller_slug=seller_slug,
    )


def get_cached_stats(key: str):
    return cache.get(key)


def set_cached_stats(key: str, value, ttl: int | None = None) -> None:
    cache.set(key, value, ttl if ttl is not None else _stats_ttl())
