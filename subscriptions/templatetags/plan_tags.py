"""Tarifs et quotas des plans dans les templates, lus dans PlanConfig.

    {% load plan_tags %}
    {% plan_price "pro" as pro_price %}{{ pro_price|floatformat:"0g" }} FCFA
    {% plan_quota_label "pro" %}   -> « Ventes flash illimitées » / « 50 ventes flash par mois »

Jamais de montant ou de quota ecrit en dur dans un template (garde-fou :
subscriptions/tests_plans.py).
"""

from __future__ import annotations

from django import template

from subscriptions.services.plans import get_official_price, quota_label

register = template.Library()


@register.simple_tag
def plan_price(plan: str) -> int:
    return get_official_price(plan)


@register.simple_tag
def plan_quota_label(plan: str) -> str:
    return quota_label(plan)
