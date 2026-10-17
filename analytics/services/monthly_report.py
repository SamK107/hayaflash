"""Bilan mensuel d'une boutique (lecture seule) — réutilisable côté admin et vendeuse.

Définitions retenues (vérifiées dans le code) :

* **Commande réalisée** = « encaissée » au sens de ``orders.services.dashboard.collected_q``
  (F-94/F-95) : ``Order.status == DELIVERED`` **et** ``Delivery.cod_collected``. C'est la
  même définition que l'analytique vendeuse : admin et vendeuse voient les mêmes chiffres.
* **Chiffre d'affaires réalisé** = somme ``price_snapshot × quantity`` des lignes des
  commandes réalisées (prix enregistré sur la ligne, jamais le prix catalogue).
* **Mois d'une commande** = mois de ``Order.created_at`` en heure locale
  (``TIME_ZONE``) : bornes ``[1er du mois 00:00, 1er du mois suivant 00:00[`` locales.
* Répartition des commandes passées (catégories exclusives, somme = total) :
  réalisées · annulées (``CANCELLED``) · livrées non encaissées (``DELIVERED`` sans COD
  encaissé) · échec de livraison (``Delivery.status == FAILED``, commande ni annulée
  ni livrée) · en attente de mise à jour (tout le reste : pending, confirmed,
  out_for_delivery).
* **Ventes flash réalisées** = ventes non annulées dont le début tombe dans le mois
  (et déjà commencé).
* **Clientes** = téléphones distincts des commandes réalisées du mois ; « déjà clientes »
  = téléphones ayant une commande non annulée chez cette boutique avant le mois.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from accounts.models import SellerProfile
from analytics.services.reporting import _collected_items, _revenue_expr
from delivery.models import Delivery
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus
from orders.services.dashboard import collected_q

ACTIVE_WINDOW_DAYS = 30
PENDING_ALERT_RATIO = 0.20

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def month_label(year: int, month: int) -> str:
    return f"{MOIS_FR[month - 1]} {year}"


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Bornes aware (heure locale) du mois : début inclus, fin exclue."""
    tz = timezone.get_current_timezone()
    start = datetime(year, month, 1, tzinfo=tz)
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, datetime(ny, nm, 1, tzinfo=tz)


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def current_month(today: date | None = None) -> tuple[int, int]:
    today = today or timezone.localdate()
    return today.year, today.month


def default_month(today: date | None = None) -> tuple[int, int]:
    """Dernier mois complet (en janvier : décembre de l'année précédente)."""
    return previous_month(*current_month(today))


def parse_month(raw: str | None) -> tuple[int, int] | None:
    """« AAAA-MM » -> (année, mois), ``None`` si invalide."""
    try:
        year_s, month_s = (raw or "").split("-")
        year, month = int(year_s), int(month_s)
    except ValueError:
        return None
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return year, month


def month_choices(
    registered_at: datetime, today: date | None = None
) -> list[dict]:
    """Mois du mois d'inscription au mois en cours, le plus récent d'abord."""
    cur = current_month(today)
    reg = timezone.localtime(registered_at)
    year, month = reg.year, reg.month
    out: list[dict] = []
    while (year, month) <= cur:
        label = month_label(year, month)
        out.append(
            {
                "value": f"{year}-{month:02d}",
                "label": label + (" (en cours)" if (year, month) == cur else ""),
            }
        )
        year, month = next_month(year, month)
    out.reverse()
    return out


def effective_plan(seller: SellerProfile) -> str:
    """Plan effectif : un plan payant expiré retombe sur Gratuit."""
    sub = getattr(seller, "subscription", None)
    if sub is None or sub.is_free:
        return "free"
    return sub.plan


def wa_link(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"https://wa.me/{digits}" if digits else ""


# --------------------------------------------------------------------------- liste


def list_shops(*, search: str = "", newest_first: bool = False) -> list[dict]:
    """Toutes les boutiques par ordre d'inscription — une seule requête agrégée."""
    now = timezone.now()
    sellers = (
        SellerProfile.objects.select_related("user", "subscription")
        .annotate(
            last_sale=Max(
                "flash_sales__start_time",
                filter=~Q(flash_sales__status=FlashSaleStatus.CANCELLED)
                & Q(flash_sales__start_time__lte=now),
            )
        )
        .order_by("created_at", "pk")
    )
    rows = []
    threshold = now - timedelta(days=ACTIVE_WINDOW_DAYS)
    for rank, seller in enumerate(sellers, start=1):
        rows.append(
            {
                "rank": rank,
                "seller": seller,
                "name": seller.business_name or seller.user.display_name,
                "phone": seller.user.phone,
                "wa_url": wa_link(seller.user.phone),
                "registered_at": seller.created_at,
                "plan": effective_plan(seller),
                "last_sale": seller.last_sale,
                "is_active": bool(seller.last_sale and seller.last_sale >= threshold),
            }
        )
    needle = search.strip().lower()
    if needle:
        digits = "".join(ch for ch in needle if ch.isdigit())
        rows = [
            r
            for r in rows
            if needle in r["name"].lower()
            or needle in r["seller"].user.display_name.lower()
            or (digits and digits in "".join(c for c in r["phone"] if c.isdigit()))
        ]
    if newest_first:
        rows.reverse()
    return rows


# --------------------------------------------------------------------------- fiche


def shop_last_sale(seller: SellerProfile):
    return FlashSale.objects.filter(
        owner=seller, start_time__lte=timezone.now()
    ).exclude(status=FlashSaleStatus.CANCELLED).aggregate(m=Max("start_time"))["m"]


def shop_month_report(seller: SellerProfile, year: int, month: int) -> dict:
    """Fiche de résultats d'une boutique pour un mois donné."""
    start, end = month_bounds(year, month)
    now = timezone.now()

    sales_count = (
        FlashSale.objects.filter(
            owner=seller, start_time__gte=start, start_time__lt=min(end, now)
        )
        .exclude(status=FlashSaleStatus.CANCELLED)
        .count()
    )

    orders = Order.service_objects.filter(
        flash_sale__owner=seller, created_at__gte=start, created_at__lt=end
    )
    realized_q = collected_q("")
    cancelled_q = Q(status=OrderStatus.CANCELLED)
    delivered_unpaid_q = Q(status=OrderStatus.DELIVERED) & ~realized_q
    failed_q = (
        Q(delivery__status=Delivery.Status.FAILED)
        & ~cancelled_q
        & ~Q(status=OrderStatus.DELIVERED)
    )
    agg = orders.aggregate(
        placed=Count("pk"),
        realized=Count("pk", filter=realized_q),
        cancelled=Count("pk", filter=cancelled_q),
        delivered_unpaid=Count("pk", filter=delivered_unpaid_q),
        failed=Count("pk", filter=failed_q),
    )
    placed = agg["placed"]
    pending = (
        placed
        - agg["realized"]
        - agg["cancelled"]
        - agg["delivered_unpaid"]
        - agg["failed"]
    )
    realized = agg["realized"]

    items = _collected_items().filter(
        order__flash_sale__owner=seller,
        order__created_at__gte=start,
        order__created_at__lt=end,
    )
    totals = items.aggregate(
        revenue=Sum(_revenue_expr()), quantity=Sum("quantity")
    )
    revenue = int(totals["revenue"] or 0)
    quantity = totals["quantity"] or 0

    product_rows = list(
        items.values("product_name_snapshot")
        .annotate(qty=Sum("quantity"), revenue=Sum(_revenue_expr()))
        .order_by("-revenue", "product_name_snapshot")
    )
    products = []
    cumulative = 0.0
    for row in product_rows:
        rev = int(row["revenue"] or 0)
        share = (rev / revenue * 100) if revenue else 0.0
        cumulative += share
        products.append(
            {
                "name": row["product_name_snapshot"],
                "quantity": row["qty"] or 0,
                "revenue": rev,
                "share": round(share, 1),
                "cumulative": round(min(cumulative, 100.0), 1),
            }
        )
    if products:
        products[-1]["cumulative"] = 100.0 if revenue else 0.0

    phones = {
        p
        for p in orders.filter(realized_q)
        .exclude(customer_phone__isnull=True)
        .exclude(customer_phone="")
        .values_list("customer_phone", flat=True)
        .distinct()
    }
    returning = 0
    if phones:
        returning = (
            Order.service_objects.filter(
                flash_sale__owner=seller,
                created_at__lt=start,
                customer_phone__in=phones,
            )
            .exclude(status=OrderStatus.CANCELLED)
            .values("customer_phone")
            .distinct()
            .count()
        )

    return {
        "year": year,
        "month": month,
        "label": month_label(year, month),
        "is_current": (year, month) == current_month(),
        "sales_count": sales_count,
        "orders_placed": placed,
        "orders_realized": realized,
        "orders_cancelled": agg["cancelled"],
        "orders_delivered_unpaid": agg["delivered_unpaid"],
        "orders_failed": agg["failed"],
        "orders_pending_update": pending,
        "realization_rate": round(realized / placed * 100) if placed else None,
        "pending_alert": bool(placed and pending / placed > PENDING_ALERT_RATIO),
        "revenue": revenue,
        "items_sold": quantity,
        "average_basket": round(revenue / realized) if realized else 0,
        "products": products,
        "customers": len(phones),
        "customers_returning": returning,
        "is_empty": sales_count == 0 and placed == 0,
    }
