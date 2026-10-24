"""Balise du bandeau d'invitation (spec §5.2) : UN seul `{% include %}` dans le tableau de bord
vendeur (`templates/seller/home.html`). Jamais d'erreur propagee vers la page hote."""

from __future__ import annotations

import logging

from django import template

from distrib.access import distrib_enabled
from distrib.services.invites import accepted_invites_for, pending_invites_for

register = template.Library()
logger = logging.getLogger(__name__)


@register.inclusion_tag("distrib/_invitation_banner_body.html", takes_context=True)
def distrib_invite_banner(context):
    empty = {"invites": [], "accepted_count": 0}
    if not distrib_enabled():
        return empty
    request = context.get("request")
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return empty
    try:
        invites = list(pending_invites_for(user)[:3])
        seller = getattr(user, "seller_profile", None)
        accepted = accepted_invites_for(seller).count() if seller is not None else 0
    except Exception:  # le tableau de bord vendeur ne doit jamais casser a cause de Distrib
        logger.exception("distrib: bandeau d'invitation indisponible")
        return empty
    return {"invites": invites, "accepted_count": accepted}
