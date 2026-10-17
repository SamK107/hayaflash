"""Le Marche HayaFlash (/ventes/) : agregats des ventes affichees, en lot.

Lecture seule. Un seul calcul pour toute la page, mis en cache
``MARKET_CACHE_SECONDS`` sous la cle ``hf:market:v1`` : que 1 ou 100 acheteurs
ouvrent la page, la base voit ~5 requetes agregees toutes les 30 s (jamais une
requete par carte).

Regles d'affichage (miroir de ``live_pulse``) :
- aucun chiffre invente : stock inconnu ou nul -> ``percent_sold`` = None ;
  pourcentage sous ``MIN_PERCENT_SHOWN`` -> None ; commandes sous
  ``PROOF_MIN_ORDERS`` -> ``orders_visible`` = None ;
- aucune donnee d'acheteur (nom, telephone, adresse) dans la sortie : que des
  comptes et des champs publics de la vente / de la boutique.

La sortie ne contient que des types simples (ids, int, str, datetime) : pas
d'instances de modele dans le cache.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.db.models import Count, Sum
from django.utils import timezone

from analytics.services.live_pulse import PROOF_MIN_ORDERS

MARKET_CACHE_KEY = "hf:market:v1"
MARKET_CACHE_SECONDS = 30
MIN_PERCENT_SHOWN = 5
ENDED_LIMIT = 6


def _percent_sold(items_sold: int, stock: int | None) -> int | None:
    """Articles vendus / (vendus + stock restant), None si non fiable."""
    if stock is None or stock <= 0 or items_sold <= 0:
        return None
    pct = round(100 * items_sold / (items_sold + stock))
    return pct if pct >= MIN_PERCENT_SHOWN else None


def compute_market_snapshot(now=None) -> dict[str, Any]:
    """Calcule le snapshot (sans cache)."""
    from flash_sales.models import FlashSale
    from flash_sales.services.ordering import live_now_q, recently_ended_q
    from orders.models import Order, OrderItem, OrderStatus
    from products.models import FlashSaleProduct

    now = now or timezone.now()

    live_ids = list(FlashSale.objects.filter(live_now_q(now)).values_list("pk", flat=True))
    ended = list(
        FlashSale.objects.filter(recently_ended_q(now))
        .select_related("owner")
        .only(
            "title", "public_slug", "end_time", "category",
            "owner__business_name", "owner__public_slug", "owner__category", "owner__avatar",
        )
        .order_by("-end_time")[:ENDED_LIMIT]
    )
    ended_ids = [s.pk for s in ended]

    orders_by_sale = {
        row["flash_sale_id"]: row["n"]
        for row in Order.objects.filter(flash_sale_id__in=live_ids)
        .exclude(status=OrderStatus.CANCELLED)
        .values("flash_sale_id")
        .annotate(n=Count("id"))
    }
    items_by_sale = {
        row["order__flash_sale_id"]: row["q"] or 0
        for row in OrderItem.objects.filter(order__flash_sale_id__in=live_ids)
        .exclude(order__status=OrderStatus.CANCELLED)
        .values("order__flash_sale_id")
        .annotate(q=Sum("quantity"))
    }
    # Meme source de stock que compute_live_pulse : produits actifs de la vente.
    stock_by_sale = {
        row["flash_sale_id"]: row["stock"]
        for row in FlashSaleProduct.objects.filter(
            flash_sale_id__in=live_ids + ended_ids, is_active=True, product__is_active=True
        )
        .values("flash_sale_id")
        .annotate(stock=Sum("product__stock_available"))
    }

    sales: dict[int, dict[str, Any]] = {}
    for pk in live_ids:
        orders = orders_by_sale.get(pk, 0)
        items = items_by_sale.get(pk, 0)
        sales[pk] = {
            "orders": orders,
            "orders_visible": orders if orders >= PROOF_MIN_ORDERS else None,
            "items_sold": items,
            "percent_sold": _percent_sold(items, stock_by_sale.get(pk)),
        }

    recently_ended = []
    for s in ended:
        owner = s.owner
        stock = stock_by_sale.get(s.pk)
        recently_ended.append(
            {
                "id": s.pk,
                "title": s.title,
                "public_slug": s.public_slug,
                "end_time": s.end_time,
                "category": s.effective_category,
                "category_label": s.effective_category_label,
                "shop_name": owner.business_name,
                "shop_slug": owner.public_slug,
                "shop_avatar_url": owner.avatar.url if owner.avatar else "",
                # Pas de compteur de commandes sur une vente terminee.
                "sold_out": stock is not None and stock <= 0,
            }
        )

    return {"sales": sales, "recently_ended": recently_ended}


def get_market_snapshot(now=None) -> dict[str, Any]:
    """Snapshot du Marche, cache 30 s sous une seule cle pour toute la page.

    ``sales`` : {id vente en direct -> orders, orders_visible, items_sold,
    percent_sold} ; ``recently_ended`` : jusqu'a 6 ventes terminees depuis moins
    de 2 h, la plus recente d'abord. ``now`` ne sert qu'au calcul (tests).
    """
    data = cache.get(MARKET_CACHE_KEY)
    if data is None:
        data = compute_market_snapshot(now)
        cache.set(MARKET_CACHE_KEY, data, timeout=MARKET_CACHE_SECONDS)
    return data
