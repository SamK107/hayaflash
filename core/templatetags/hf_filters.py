from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def thousands(value) -> str:
    """Format a number with a space as thousands separator (e.g. 40000 -> '40 000')."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", " ")
