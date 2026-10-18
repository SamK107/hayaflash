"""Reperage des donnees de demo (seed_marche_demo) : prefixes et visibilite.

Les comptes vendeurs de demo ont un telephone ``DEMO_PHONE_PREFIX...`` ; les
commandes de demo, des telephones clients ``DEMO_CLIENT_PREFIX...``.
"""

from __future__ import annotations

import os

from django.conf import settings

DEMO_PHONE_PREFIX = "+22379990"    # comptes vendeurs
DEMO_CLIENT_PREFIX = "+22378880"   # telephones clients des commandes de demo
ALLOW_ENV_VAR = "HAYAFLASH_ALLOW_DEMO_SEED"

# Hotes de production : source unique pour le garde-fou de la commande
# seed_marche_demo ET celui du demarrage (config/settings/prod.py).
PRODUCTION_HOSTS = frozenset({"hayaflash.com", "www.hayaflash.com"})


def has_production_host(allowed_hosts) -> bool:
    """Vrai si ALLOWED_HOSTS vise la production (hayaflash.com, www, .hayaflash.com ou ``*``)."""
    for host in allowed_hosts:
        h = str(host).strip().lower()
        if h == "*" or h.lstrip(".") in PRODUCTION_HOSTS:
            return True
    return False


def demo_data_visible() -> bool:
    """Vrai en dev (DEBUG) et sur un staging qui a active le seed de demo.

    Faux ailleurs (production) : les boutiques de demo n'y sont jamais comptees.
    """
    return bool(settings.DEBUG) or os.environ.get(ALLOW_ENV_VAR) == "1"
