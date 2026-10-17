"""Entree « Le Marche » adaptative de l'accueil : etat reel des ventes.

Trois etats, une seule requete agregee, cache ``MARKET_ENTRY_CACHE_SECONDS`` :
- ``live``  : N ventes en direct -> « Le Marché · N en direct » ;
- ``soon``  : aucune en direct mais une vente commence dans les 24 h ->
  « Prochaine vente : aujourd'hui 20 h » (ou « demain 18 h ») ;
- ``idle``  : simple lien « Le Marché ».

Aucun chiffre invente. Les boutiques de demo (``seed_marche_demo``) ne sont
comptees qu'en dev et sur un staging qui a active le seed (``demo_data_visible``).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Min, Q
from django.utils import timezone

from core.demo_data import DEMO_PHONE_PREFIX, demo_data_visible
from flash_sales.services.ordering import live_now_q, upcoming_q

MARKET_ENTRY_CACHE_KEY = "hf:market:entry:v1"
MARKET_ENTRY_CACHE_SECONDS = 30
SOON_HORIZON = timedelta(hours=24)


def _hour_label(local_dt) -> str:
    return f"{local_dt.hour} h" + (f" {local_dt.minute:02d}" if local_dt.minute else "")


def compute_market_entry(now=None) -> dict[str, Any]:
    from flash_sales.models import FlashSale

    now = now or timezone.now()
    sales = FlashSale.objects.all()
    if not demo_data_visible():
        sales = sales.exclude(owner__user__phone__startswith=DEMO_PHONE_PREFIX)
    agg = sales.aggregate(
        live=Count("id", filter=live_now_q(now)),
        next_start=Min("start_time", filter=upcoming_q(now) & Q(start_time__lte=now + SOON_HORIZON)),
    )
    live, next_start = agg["live"], agg["next_start"]
    if live:
        return {"state": "live", "live": live, "label": f"Le Marché · {live} en direct"}
    if next_start is not None:
        local = timezone.localtime(next_start)
        same_day = local.date() == timezone.localtime(now).date()
        when = ("aujourd'hui " if same_day else "demain ") + _hour_label(local)
        return {"state": "soon", "live": 0, "label": f"Prochaine vente : {when}"}
    return {"state": "idle", "live": 0, "label": "Le Marché"}


def get_market_entry(now=None) -> dict[str, Any]:
    data = cache.get(MARKET_ENTRY_CACHE_KEY)
    if data is None:
        data = compute_market_entry(now)
        cache.set(MARKET_ENTRY_CACHE_KEY, data, timeout=MARKET_ENTRY_CACHE_SECONDS)
    return data
