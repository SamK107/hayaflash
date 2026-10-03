from __future__ import annotations

from django import template

from core.countries import COUNTRIES, DEFAULT_COUNTRY

register = template.Library()


@register.inclusion_tag("partials/_interest_phone.html")
def interest_phone_field(sfx: str) -> dict:
    """Champ telephone des tiroirs « M'alerter » : selecteur d'indicatif + numero national."""
    return {"sfx": sfx, "countries": COUNTRIES, "default_country": DEFAULT_COUNTRY}
