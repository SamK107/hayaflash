"""Le Marche HayaFlash, phase 2a : indices publics du jour (/ventes/).

Lecture seule. Indicateurs agreges, toutes boutiques confondues :
commandes de la derniere heure, categories les plus demandees, livraisons en
cours, commandes par heure (sparkline). Aucune donnee par boutique, ni nom, ni
volume, ni produit ; aucun chiffre invente : tout vient des requetes, un
indicateur sous son seuil est masque (None / absent).

Charge : ``get_market_stats`` = 4 requetes agregees a froid, 0 a chaud (cache
``MARKET_STATS_CACHE_SECONDS`` sous une seule cle par jour Africa/Bamako).

Commandes comptees : tout statut sauf ``CANCELLED``. Il n'existe ni brouillon ni
statut d'echec de paiement sur ``Order`` (paiement a la livraison en V1).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Value
from django.db.models.functions import Coalesce, NullIf, TruncHour
from django.utils import timezone

from core.choices import SaleCategory

# ── Seuils d'affichage (sous le seuil : indicateur masque) ────────────────
MARKET_MIN_ORDERS_HOUR = 3      # commandes de la derniere heure
MARKET_MIN_SHOPS_PER_CATEGORY = 2  # boutiques distinctes pour citer une categorie
MARKET_MIN_DELIVERIES = 3       # livraisons en cours
MARKET_MIN_ORDERS_DAY = 5       # commandes du jour pour tracer la sparkline
MARKET_TOP_CATEGORIES = 3

MARKET_STATS_CACHE_SECONDS = 60
MARKET_STATS_CACHE_KEY = "hf:market:stats:v1:{day}"

SPARK_WIDTH = 240
SPARK_HEIGHT = 48
_SPARK_PAD = 4


def _sparkline(hourly: list[int]) -> dict[str, Any]:
    """Points SVG (viewBox SPARK_WIDTH x SPARK_HEIGHT) d'une serie horaire."""
    peak = max(hourly) or 1
    n = len(hourly)
    inner_h = SPARK_HEIGHT - 2 * _SPARK_PAD
    coords = [
        (
            round(i * SPARK_WIDTH / (n - 1), 1),
            round(SPARK_HEIGHT - _SPARK_PAD - v / peak * inner_h, 1),
        )
        for i, v in enumerate(hourly)
    ]
    line = " ".join(f"{x},{y}" for x, y in coords)
    area = f"0,{SPARK_HEIGHT} {line} {SPARK_WIDTH},{SPARK_HEIGHT}"
    return {
        "hours": hourly,  # une valeur par heure, de 0 h a l'heure courante
        "points": line,
        "area": area,
        "peak": max(hourly),
        "width": SPARK_WIDTH,
        "height": SPARK_HEIGHT,
    }


def compute_market_stats(now=None) -> dict[str, Any]:
    """Calcule les indicateurs (sans cache). Cles absentes/None = masque."""
    from delivery.models import Delivery
    from orders.models import Order, OrderStatus

    now = now or timezone.now()
    local_now = timezone.localtime(now)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    valid = Order.service_objects.exclude(status=OrderStatus.CANCELLED)
    today = valid.filter(created_at__gte=day_start, created_at__lte=now)

    # 1. Commandes par heure (aujourd'hui), tronquees dans le fuseau local.
    by_hour = {
        timezone.localtime(row["h"]).hour: row["n"]
        for row in today.annotate(h=TruncHour("created_at", tzinfo=local_now.tzinfo))
        .values("h")
        .annotate(n=Count("id"))
    }
    hourly = [by_hour.get(h, 0) for h in range(local_now.hour + 1)]
    orders_today = sum(hourly)

    # 2. Commandes de la derniere heure (peut deborder sur la veille a minuit).
    last_hour = valid.filter(
        created_at__gte=now - timedelta(hours=1), created_at__lte=now
    ).count()

    # 3. Categories : celle de la vente, sinon celle de la boutique, sinon "autre".
    category = Coalesce(
        NullIf("flash_sale__category", Value("")),
        NullIf("flash_sale__owner__category", Value("")),
        Value(SaleCategory.AUTRE),
    )
    rows = (
        today.filter(flash_sale__isnull=False)
        .annotate(cat=category)
        .values("cat")
        .annotate(n=Count("id"), shops=Count("flash_sale__owner", distinct=True))
        .filter(shops__gte=MARKET_MIN_SHOPS_PER_CATEGORY)
        .order_by("-n", "cat")[:MARKET_TOP_CATEGORIES]
    )
    labels = dict(SaleCategory.choices)
    top_categories = [labels.get(r["cat"], r["cat"]) for r in rows]

    # 4. Livraisons en cours (statut Delivery.IN_TRANSIT ; pas de champ ville).
    in_transit = (
        Delivery.objects.filter(status=Delivery.Status.IN_TRANSIT)
        .exclude(order__status=OrderStatus.CANCELLED)
        .count()
    )

    stats: dict[str, Any] = {
        "orders_last_hour": last_hour if last_hour >= MARKET_MIN_ORDERS_HOUR else None,
        "top_categories": top_categories,
        "deliveries_in_transit": in_transit if in_transit >= MARKET_MIN_DELIVERIES else None,
        "sparkline": (
            _sparkline(hourly)
            if orders_today >= MARKET_MIN_ORDERS_DAY and len(hourly) >= 2
            else None
        ),
        "spark_to_hour": local_now.hour,
    }
    stats["visible"] = bool(
        stats["orders_last_hour"]
        or stats["top_categories"]
        or stats["deliveries_in_transit"]
        or stats["sparkline"]
    )
    return stats


def get_market_stats(now=None) -> dict[str, Any]:
    """Indicateurs du jour, caches 60 s sous une seule cle par jour."""
    now = now or timezone.now()
    key = MARKET_STATS_CACHE_KEY.format(day=timezone.localtime(now).date().isoformat())
    data = cache.get(key)
    if data is None:
        data = compute_market_stats(now)
        cache.set(key, data, timeout=MARKET_STATS_CACHE_SECONDS)
    return data

