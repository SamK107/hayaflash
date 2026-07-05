from __future__ import annotations

import re
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_text(label: str, *, max_length: int = 60, fallback: str = "item") -> str:
    """Single source of truth for SEO-safe slug fragments."""
    normalized = (label or "").strip().lower()
    normalized = _SLUG_RE.sub("-", normalized).strip("-")
    if not normalized:
        normalized = fallback
    return normalized[:max_length].rstrip("-")


def unique_slug_for_model(
    model_class: type,
    *,
    field_name: str,
    base: str,
    exclude_pk: int | None = None,
    max_length: int = 80,
) -> str:
    """Deterministic base slug; numeric suffix until unique within ``field_name``."""
    candidate = base[:max_length]
    suffix = 2
    qs = model_class.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(**{field_name: candidate}).exists():
        tail = f"-{suffix}"
        candidate = f"{base[: max(1, max_length - len(tail))]}{tail}"
        suffix += 1
    return candidate


def seller_slug_base(*, business_name: str, display_name: str) -> str:
    label = (business_name or display_name or "store").strip()
    return slugify_text(label, max_length=60, fallback="store")


def flash_sale_slug_base(title: str) -> str:
    return slugify_text(title, max_length=70, fallback="vente-flash")
