"""Production: PostgreSQL, strict hosts, no DEBUG, JSON API only."""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK as BASE_REST_FRAMEWORK
from core.demo_data import ALLOW_ENV_VAR, has_production_host

from ._sentry import init_sentry
from .base import REDIS_URL, SECRET_KEY, SENTRY_DSN, _csv  # noqa: F401

# ── Sentry ────────────────────────────────────────────────────────────────────
init_sentry(SENTRY_DSN, environment="prod")

DEBUG = False

# Sans Redis, les caches seraient LocMem PAR PROCESSUS (3 workers Gunicorn) :
# verrous axes, limites de debit et honeypot perdraient leur efficacite sans
# aucune erreur visible. On refuse donc de demarrer (F anti-bot, decision 8).
if not REDIS_URL:
    raise ImproperlyConfigured(
        "REDIS_URL must be set in the environment for production (shared cache: "
        "axes lockouts and rate limits need it across Gunicorn workers)."
    )

if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in the environment for production."
    )

try:
    raw_hosts = os.environ["ALLOWED_HOSTS"]
except KeyError as exc:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set in the environment for production "
        "(comma-separated list)."
    ) from exc

ALLOWED_HOSTS = [h.strip() for h in raw_hosts.split(",") if h.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must contain at least one non-empty hostname."
    )

# Garde-fou demo (PP-01) : la variable de seed de demo rend visibles les
# boutiques de demo (core/demo_data.py:demo_data_visible) ; sur un hote de
# production elle exposerait de fausses donnees aux vrais clients.
if os.environ.get(ALLOW_ENV_VAR) == "1" and has_production_host(ALLOWED_HOSTS):
    raise ImproperlyConfigured(
        f"Variable de démo interdite en production : {ALLOW_ENV_VAR}=1 alors que "
        "ALLOWED_HOSTS contient un hôte de production (hayaflash.com, "
        "www.hayaflash.com, .hayaflash.com ou *). Retirer la variable du .env."
    )

# Staging non indexable (D8) : sur tout hote qui n'est PAS un hote de production,
# robots.txt interdit tout et chaque reponse porte X-Robots-Tag: noindex, nofollow.
# Jamais en production : HAYAFLASH_NOINDEX=1 avec un hote de production = refus de
# demarrer (le site disparaitrait des moteurs de recherche).
if os.environ.get("HAYAFLASH_NOINDEX") == "1" and has_production_host(ALLOWED_HOSTS):
    raise ImproperlyConfigured(
        "HAYAFLASH_NOINDEX=1 interdit sur un hote de production : le site ne serait "
        "plus indexable. Retirer la variable du .env."
    )
# Par defaut : noindex sur tout hote non production (staging) ; HAYAFLASH_NOINDEX=0
# permet de le desactiver explicitement sur un hote de test.
SITE_NOINDEX = (
    False
    if os.environ.get("HAYAFLASH_NOINDEX") == "0"
    else not has_production_host(ALLOWED_HOSTS)
)

# www -> domaine nu, redirection permanente (D14). Le domaine www doit etre dans
# ALLOWED_HOSTS, declare dans HestiaCP et couvert par le certificat.
CANONICAL_HOST_REDIRECTS = {"www.hayaflash.com": "hayaflash.com"}

CORS_ALLOW_ALL_ORIGINS = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Proxy de confiance pour l'IP client (F-26) : Gunicorn n'est joignable que par
# le Nginx du conteneur (`expose`, jamais publie), sur le reseau Docker. Valeur
# par defaut = plages privees RFC 1918 (reseau bridge Docker, 172.16.0.0/12
# par defaut) ; a resserrer sur le sous-reseau reel du compose en Phase 4
# (`docker network inspect`), ou a surcharger par TRUSTED_PROXY_NETWORKS.
TRUSTED_PROXY_NETWORKS = _csv(
    "TRUSTED_PROXY_NETWORKS", "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"
)
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "true").lower() in (
    "1",
    "true",
    "yes",
)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# False (defaut Django) : le JS lit csrftoken dans document.cookie pour
# l'en-tete X-CSRFToken (static/js/hf-base.js pour HTMX, hf-seller.js,
# hf-public.js). HttpOnly n'apporte pas de protection reelle ici : un script
# injecte pourrait lire le jeton dans le DOM. Voir la doc Django :
# https://docs.djangoproject.com/en/5.2/ref/settings/#csrf-cookie-httponly
# Garde-fou : core/tests_security_settings.py.
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"

# HSTS (D14) : 180 jours au lancement, SANS includeSubDomains ni preload. Ces deux
# options imposeraient HTTPS a tous les sous-domaines (staging, autres sites du
# serveur) et le preload est quasi irreversible. A revoir apres plusieurs mois
# stables. W005/W021 sont donc volontairement ignores.
SECURE_HSTS_SECONDS = 15_552_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Divers headers sécurité
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

csrf_origins = _csv("CSRF_TRUSTED_ORIGINS")
if csrf_origins:
    CSRF_TRUSTED_ORIGINS = csrf_origins

REST_FRAMEWORK = {
    **BASE_REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}
