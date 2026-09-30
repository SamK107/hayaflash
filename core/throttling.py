"""Throttles DRF identifiant le client via l'unique extraction d'IP (F-26).

DRF lit sinon l'en-tete X-Forwarded-For entier (NUM_PROXIES non defini), que
le client peut changer a chaque requete pour echapper a la limite.
"""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from core.services.client_ip import get_client_ip


class TrustedProxyAnonRateThrottle(AnonRateThrottle):
    def get_ident(self, request):
        return get_client_ip(request)


class TrustedProxyUserRateThrottle(UserRateThrottle):
    def get_ident(self, request):
        return get_client_ip(request)
