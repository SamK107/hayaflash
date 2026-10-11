"""Lien public personnel d'un partenaire /r/<code>/ : atterrissage sur l'accueil."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.services import rate_limit
from partners.models import PartnerClick
from partners.services.attribution import (
    COOKIE_NAME,
    find_partner_for_new_referral,
    request_ip_hash,
)


@require_GET
def referral_link_view(request, code: str):
    """Enregistre le clic, pose le cookie, puis renvoie vers l'accueil (F-122).

    Code inconnu, partenaire inactif ou contrat expiré : même réponse (302 vers
    l'accueil), sans cookie ni message ni clic. Cible fixe : aucune redirection ouverte.
    Au-delà de la limite par IP, même réponse, sans clic ni cookie. L'accueil affiche une
    bannière d'inscription seulement si le cookie désigne un partenaire éligible.
    """
    response = HttpResponseRedirect(reverse("home"))
    if rate_limit.referral_ip_limited(request):
        return response
    partner = find_partner_for_new_referral(code)
    if partner is None:
        return response
    PartnerClick.objects.create(partner=partner, ip_hash=request_ip_hash(request))
    response.set_cookie(
        COOKIE_NAME,
        partner.code,
        max_age=settings.PARTNER_REFERRAL_COOKIE_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="Lax",
    )
    return response
