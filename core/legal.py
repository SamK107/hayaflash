"""Documents légaux (CGU, politique de confidentialité) : versions courantes.

Source unique des numéros de version : pages légales, inscription web et API
les lisent ici. Changer une version = nouveau texte à faire accepter aux
nouveaux inscrits (les acceptations passées restent liées à leur version).
"""

from __future__ import annotations

import datetime

from django.utils import timezone

LEGAL_CGU_VERSION = "2026-09"
LEGAL_PRIVACY_VERSION = "2026-09"

# Date affichée « Dernière mise à jour » sur les pages légales.
LEGAL_LAST_UPDATED = datetime.date(2026, 9, 27)


# Même message pour le formulaire web et l'API d'inscription.
LEGAL_ACCEPTANCE_REQUIRED_MESSAGE = (
    "Vous devez accepter les CGU et la politique de confidentialité."
)


def acceptance_ip(request) -> str | None:
    """IP du client pour la preuve d'acceptation, ou None si inexploitable.

    Utilise l'unique extraction d'IP (core.services.client_ip) : l'en-tete du
    proxy de confiance, jamais un X-Forwarded-For fourni par le client. On ne
    garde qu'une IP valide (GenericIPAddressField).
    """
    from core.services.client_ip import get_client_ip_or_none

    return get_client_ip_or_none(request)


def record_legal_acceptances(user, request=None) -> list:
    """Enregistre l'acceptation des CGU et de la politique (versions courantes).

    À appeler dans la même transaction que la création du compte.
    """
    from core.models import LegalAcceptance, LegalDocument

    ip = acceptance_ip(request)
    now = timezone.now()
    return [
        LegalAcceptance.objects.create(
            user=user, document=document, version=version, accepted_at=now, ip_address=ip
        )
        for document, version in (
            (LegalDocument.CGU, LEGAL_CGU_VERSION),
            (LegalDocument.PRIVACY, LEGAL_PRIVACY_VERSION),
        )
    ]
