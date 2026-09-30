from __future__ import annotations

from django import template

from core.services import honeypot

register = template.Library()


@register.inclusion_tag("partials/_honeypot.html")
def honeypot_fields() -> dict:
    return {
        "honeypot_field": honeypot.HONEYPOT_FIELD,
        "timestamp_field": honeypot.TIMESTAMP_FIELD,
        "token": honeypot.make_token(),
    }
