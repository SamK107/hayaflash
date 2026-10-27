"""Balise du bandeau d'invitation (spec §5.2) : UN seul `{% include %}` dans le tableau de bord
vendeur (`templates/seller/home.html`). Jamais d'erreur propagee vers la page hote."""

from __future__ import annotations

import logging

from django import template
from django.template.loader import render_to_string

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


# ── Confirmation cliente (SPEC_03 §15.3) ──────────────────────────────────

# Pages sur lesquelles le lien et le bandeau n'ont rien a faire (espaces vendeur, admin, module Distrib, API).
_HIDDEN_PREFIXES = ("/seller/", "/platform-admin/", "/admin/", "/distrib/", "/api/", "/billing/", "/orders/")


@register.simple_tag(takes_context=True)
def distrib_public_hooks(context):
    """Pied des pages publiques : lien « Confirmer un paiement » + conteneur du bandeau.

    UN seul `{% include %}` dans `templates/base.html`. Le fragment est identique pour tous les
    visiteurs (donc sans risque de cache) ; le bandeau est charge par `fetch` depuis un endpoint prive.
    Interrupteur coupe, page vendeur/admin ou erreur : rien n'est rendu."""
    if not distrib_enabled():
        return ""
    try:
        request = context.get("request")
        path = getattr(request, "path", "") or ""
        if not path or path.startswith(_HIDDEN_PREFIXES):
            return ""
        return render_to_string("distrib/_public_hooks_body.html")
    except Exception:
        logger.exception("distrib: pied de page public indisponible")
        return ""


@register.simple_tag(takes_context=True)
def distrib_receipt_hint(context, parcours="order"):
    """Ecran de confirmation de commande : code a 4 chiffres (acces 1).

    `parcours="order"` : page /order/ (variable Alpine `submitted`, jeton CSRF dans le HTML, page non cachee).
    `parcours="drawer"` : tiroir de /f/<slug>/ (`orderSuccess`, telephone `submittedPhone`, page publique cachee :
    aucun jeton dans le HTML)."""
    if not distrib_enabled():
        return ""
    try:
        if parcours == "drawer":
            ctx = {"watch": "orderSuccess", "phone_expr": "$data.submittedPhone", "csrf_token": ""}
        else:
            ctx = {"watch": "submitted", "phone_expr": "''", "csrf_token": context.get("csrf_token", "")}
        return render_to_string("distrib/_receipt_hint_body.html", ctx)
    except Exception:
        logger.exception("distrib: rappel du code de commande indisponible")
        return ""
