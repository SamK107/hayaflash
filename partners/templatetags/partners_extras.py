from django import template

from partners.services.payouts import fmt

register = template.Library()


@register.filter
def fcfa(value) -> str:
    """Montant en FCFA entiers, milliers séparés par une espace (jamais de centimes)."""
    try:
        return fmt(int(value or 0))
    except (TypeError, ValueError):
        return "0"
