"""Pouls d'une vente flash : stock en temps reel + preuve sociale.

Phase 10.1 / 10.3 (rarete par defaut, pour tous les vendeurs) : la page
publique /f/<slug>/ interroge GET /f/<slug>/pulse/ toutes les ~15 s pendant
la vente pour que le stock affiche baisse aussi quand ce sont d'AUTRES
acheteurs qui commandent, et pour afficher une preuve sociale reelle.

Regles d'affichage (appliquees cote client ET dans le rendu initial) :
- Aucun chiffre invente, aucun nom/telephone d'acheteur expose.
- Les chiffres trop faibles ne sont pas montres (``PROOF_MIN_*``) : "1 personne
  attend" dessert la vente plus qu'il ne la sert.

Charge : resultat mis en cache ``PULSE_CACHE_SECONDS`` par vente (cache
partage Redis en staging/prod) -> 100 acheteurs qui pollent = ~1 calcul
toutes les 5 s, pas 100.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

PULSE_CACHE_SECONDS = 5
RECENT_WINDOW_MINUTES = 10
PROOF_MIN_INTERESTED = 3
PROOF_MIN_ORDERS = 1


def pulse_cache_key(slug: str) -> str:
    return f"hf:pulse:{slug}"


def compute_live_pulse(flash_sale) -> dict[str, Any]:
    """Calcule le pouls (sans cache). ``flash_sale`` : instance FlashSale."""
    from analytics.services.public_pages import _flash_sale_page_state
    from orders.models import Order, OrderItem, OrderStatus
    from products.services.crud import products_for_sale

    now = timezone.now()
    is_live = flash_sale.is_live()
    state = _flash_sale_page_state(flash_sale, is_live=is_live)

    orders = Order.objects.filter(flash_sale=flash_sale).exclude(
        status=OrderStatus.CANCELLED
    )
    agg = orders.aggregate(
        n=Count("id"),
        recent=Count(
            "id", filter=Q(created_at__gte=now - timedelta(minutes=RECENT_WINDOW_MINUTES))
        ),
        last=Max("created_at"),
    )
    items_sold = (
        OrderItem.objects.filter(order__in=orders).aggregate(q=Sum("quantity"))["q"] or 0
    )
    # Un meme numero inscrit deux fois ne compte qu'une fois.
    interested = flash_sale.interests.values("phone").distinct().count()

    last = agg["last"]
    stock = {}
    if state == "live":
        stock = {
            str(p.pk): max(0, int(p.stock_available or 0))
            for p in products_for_sale(flash_sale, only_active=True)
            if p.stock_available is not None
        }

    return {
        "state": state,
        "end_ts_ms": int(flash_sale.end_time.timestamp() * 1000),
        "stock": stock,
        "orders": agg["n"] or 0,
        "recent_orders": agg["recent"] or 0,
        "recent_window_minutes": RECENT_WINDOW_MINUTES,
        "last_order_seconds_ago": int((now - last).total_seconds()) if last else None,
        "items_sold": items_sold,
        "interested": interested,
        "thresholds": {
            "interested": PROOF_MIN_INTERESTED,
            "orders": PROOF_MIN_ORDERS,
        },
    }


def get_live_pulse(flash_sale) -> dict[str, Any]:
    key = pulse_cache_key(flash_sale.public_slug)
    data = cache.get(key)
    if data is None:
        data = compute_live_pulse(flash_sale)
        cache.set(key, data, timeout=PULSE_CACHE_SECONDS)
    return data


def social_proof_lines(pulse: dict[str, Any]) -> dict[str, str]:
    """Textes de preuve sociale (rendu serveur initial ; miroir exact de
    ``hfPulseText`` dans static/js/hf-live-pulse.js)."""
    out = {"live": "", "live_sub": "", "waiting": ""}
    interested = pulse["interested"]
    orders = pulse["orders"]
    if interested >= PROOF_MIN_INTERESTED:
        out["waiting"] = f"{interested} personnes attendent l'ouverture"
    if orders >= PROOF_MIN_ORDERS:
        txt = f"{orders} commande{'s' if orders > 1 else ''}"
        if pulse["recent_orders"] >= 2:
            txt += f" · {pulse['recent_orders']} ces {pulse['recent_window_minutes']} dernières min"
        out["live"] = txt
        ago = pulse["last_order_seconds_ago"]
        if ago is not None and ago < 30 * 60:
            mins = ago // 60
            out["live_sub"] = (
                "Dernière commande à l'instant" if mins < 1 else f"Dernière commande il y a {mins} min"
            )
    elif interested >= PROOF_MIN_INTERESTED:
        out["live"] = f"{interested} personnes attendaient cette vente"
    return out
