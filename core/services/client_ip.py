"""IP du client : SEULE fonction d'extraction du projet (F-26).

Chaine reelle en production : client -> Nginx hote (HestiaCP, TLS) -> Nginx du
conteneur -> Gunicorn. Gunicorn ne voit donc que l'IP du Nginx du conteneur
(REMOTE_ADDR). Le Nginx du conteneur pose ``X-Real-IP`` = l'IP du client (voir
infra/nginx/prod.conf : set_real_ip_from / real_ip_header / real_ip_recursive).

Regle : on ne lit ``X-Real-IP`` QUE si la connexion directe (REMOTE_ADDR) vient
d'un proxy de confiance (settings.TRUSTED_PROXY_NETWORKS). Sinon, n'importe quel
client pourrait ecrire cet en-tete et choisir son IP (contournement des limites
de debit, fausse preuve d'acceptation des CGU, journal d'audit falsifie).
``X-Forwarded-For`` n'est JAMAIS lu : il est ajoute, pas ecrase, par la chaine
de proxys et son 1er element est fourni par le client.
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

from django.conf import settings
from django.http import HttpRequest

logger = logging.getLogger(__name__)

MAX_IP_LENGTH = 45  # taille d'une IPv6 textuelle


@lru_cache(maxsize=8)
def _parse_networks(raw: tuple[str, ...]) -> tuple:
    networks = []
    for item in raw:
        try:
            networks.append(ipaddress.ip_network(str(item).strip(), strict=False))
        except ValueError:
            logger.error("TRUSTED_PROXY_NETWORKS : reseau invalide ignore : %r", item)
    return tuple(networks)


def _is_trusted_proxy(peer: str) -> bool:
    raw = tuple(getattr(settings, "TRUSTED_PROXY_NETWORKS", ()) or ())
    if not raw:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in _parse_networks(raw))


def get_client_ip(request: HttpRequest) -> str:
    """IP du client (str, <= 45 car.), ou ``"unknown"`` si indeterminable."""
    peer = (request.META.get("REMOTE_ADDR") or "").strip()
    if peer and _is_trusted_proxy(peer):
        header = (request.META.get("HTTP_X_REAL_IP") or "").strip()
        if header:
            try:
                return str(ipaddress.ip_address(header))
            except ValueError:
                logger.warning("X-Real-IP invalide venant du proxy de confiance : ignore")
    return peer[:MAX_IP_LENGTH] or "unknown"


def get_client_ip_or_none(request: HttpRequest | None) -> str | None:
    """IP valide pour un champ GenericIPAddressField, sinon None (audit, CGU)."""
    if request is None:
        return None
    ip = get_client_ip(request)
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    return ip
