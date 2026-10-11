"""Variables d'environnement Orange Money (abonnements).

.env.example documente ORANGE_ML_* ; ORANGE_MONEY_* (nom des réglages Django) est aussi acceptée.
Règle : ORANGE_ML_* l'emporte si les deux existent et sont non vides ; sinon ORANGE_MONEY_* ;
sinon la valeur par défaut. Importé par base.py ; testé par subscriptions/tests_orange_env.py.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["orange_env", "orange_settings"]

PREFIXES = ("ORANGE_ML_", "ORANGE_MONEY_")  # par ordre de priorité
DEFAULT_TIMEOUT = 20
MAX_TIMEOUT = 120
DEFAULT_CURRENCY = "XOF"


def orange_env(environ: Mapping[str, str], suffix: str, default: str = "") -> str:
    for prefix in PREFIXES:
        value = (environ.get(prefix + suffix) or "").strip()
        if value:
            return value
    return default


def _timeout(environ: Mapping[str, str]) -> int:
    raw = orange_env(environ, "TIMEOUT")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if 0 < value <= MAX_TIMEOUT else DEFAULT_TIMEOUT


def orange_settings(environ: Mapping[str, str]) -> dict:
    """Tous les réglages ORANGE_MONEY_* calculés depuis un environnement."""
    return {
        "ORANGE_MONEY_CLIENT_ID": orange_env(environ, "CLIENT_ID"),
        "ORANGE_MONEY_CLIENT_SECRET": orange_env(environ, "CLIENT_SECRET"),
        "ORANGE_MONEY_MERCHANT_KEY": orange_env(environ, "MERCHANT_KEY"),
        "ORANGE_MONEY_BASE_URL": orange_env(environ, "BASE_URL").rstrip("/"),
        "ORANGE_MONEY_RETURN_URL": orange_env(environ, "RETURN_URL"),
        "ORANGE_MONEY_CANCEL_URL": orange_env(environ, "CANCEL_URL"),
        "ORANGE_MONEY_NOTIFY_URL": orange_env(environ, "NOTIFY_URL"),
        "ORANGE_MONEY_TIMEOUT": _timeout(environ),
        "ORANGE_MONEY_CURRENCY": orange_env(environ, "CURRENCY", DEFAULT_CURRENCY).upper(),
    }
