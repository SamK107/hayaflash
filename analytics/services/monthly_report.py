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

from collections import defaultdict
from datetime import date, datetime, timedelta

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from accounts.models import SellerProfile
from analytics.services.reporting import _collected_items, _revenue_expr
from delivery.models import Delivery
from flash_sales.models import FlashSale, FlashSaleStatus
from orders.models import Order, OrderStatus
from orders.services.dashboard import collected_q
from products.models import FlashSaleProduct

ACTIVE_WINDOW_DAYS = 30
# Part (strictement) de commandes « à mettre à jour » au-delà de laquelle on alerte.
# Compte : en attente de mise à jour + livrées non encaissées (décision 17/10).
PENDING_ALERT_RATIO = 0.20

# --- Comparaison avec le mois précédent : aucune variation si la base est trop faible.
COMPARE_MIN_REALIZED = 3  # commandes réalisées du mois précédent
COMPARE_MIN_REVENUE = 10_000  # CA réalisé du mois précédent (FCFA)
TREND_MONTHS = 3  # fenêtre d'évolution (mois sélectionné inclus)
MOVERS_LIMIT = 3  # produits en hausse / en baisse affichés

# --- Signaux « À regarder » (faits calculés, formulés neutrement).
SIGNAL_DEPENDENCE_SHARE = 40.0  # un produit > 40 % des recettes du mois
SIGNAL_SLEEPING_MIN_SALES = 2  # produit présent dans >= 2 ventes du mois, vendu 0 fois
SIGNAL_DELIVERY_RATE = 60  # taux de réalisation < 60 %...
SIGNAL_DELIVERY_MIN_ORDERS = 5  # ...avec au moins 5 commandes passées
SIGNAL_SLOT_MIN_SALES = 2  # un créneau compte s'il a >= 2 ventes ; il en faut 2 ainsi
SIGNAL_LOYAL_MIN_CUSTOMERS = 5  # part des clientes fidèles affichée si >= 5 clientes
# Créneaux de début de vente (heure locale) : matin < 12 h, après-midi < 18 h, soir.
SLOT_MORNING_END = 12
SLOT_AFTERNOON_END = 18

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
        # Décision 17/10 : les livrées non encaissées comptent aussi dans l'alerte.
        "orders_stale": pending + agg["delivered_unpaid"],
        "pending_alert": bool(
            placed
            and (pending + agg["delivered_unpaid"]) / placed > PENDING_ALERT_RATIO
        ),
        "revenue": revenue,
        "items_sold": quantity,
        "average_basket": round(revenue / realized) if realized else 0,
        "products": products,
        "customers": len(phones),
        "customers_returning": returning,
        "is_empty": sales_count == 0 and placed == 0,
    }


# ----------------------------------------------------------- partie B : bilan complet

SLOT_LABELS = {"matin": "matin", "apres_midi": "après-midi", "soir": "soir"}


def _fmt(n) -> str:
    """Entier avec séparateur de milliers (« 125 000 »)."""
    return f"{int(n):,}".replace(",", " ")


def _pct(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def slot_of(hour: int) -> str:
    if hour < SLOT_MORNING_END:
        return "matin"
    if hour < SLOT_AFTERNOON_END:
        return "apres_midi"
    return "soir"


def _variation(cur, prev, *, weak: bool, has_previous: bool, points: bool = False) -> dict:
    """Variation vs mois précédent ; jamais de pourcentage sur une base faible."""
    out = {"state": "none", "direction": "", "pct": None, "points": None}
    if not has_previous:
        return out
    if weak:
        out["state"] = "weak"
        return out
    if cur is None or prev is None:
        return out
    out["state"] = "ok"
    if cur == prev:
        out["direction"] = "equal"
    else:
        out["direction"] = "up" if cur > prev else "down"
        if points:
            out["points"] = int(cur - prev)
        elif prev:
            out["pct"] = round((cur - prev) / prev * 100)
    return out


_INDICATORS = [
    ("sales_count", "Ventes flash", "n"),
    ("orders_placed", "Commandes passées", "n"),
    ("orders_realized", "Commandes réalisées", "n"),
    ("realization_rate", "Taux de réalisation", "rate"),
    ("revenue", "CA réalisé", "fcfa"),
    ("items_sold", "Articles vendus", "n"),
    ("average_basket", "Panier moyen", "fcfa"),
]


def build_comparison(report: dict, previous: dict | None) -> dict:
    weak = bool(
        previous
        and (
            previous["orders_realized"] < COMPARE_MIN_REALIZED
            or previous["revenue"] < COMPARE_MIN_REVENUE
        )
    )
    rows = []
    for key, label, unit in _INDICATORS:
        prev_val = previous[key] if previous else None
        rows.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "value": report[key],
                "previous": prev_val,
                "variation": _variation(
                    report[key],
                    prev_val,
                    weak=weak,
                    has_previous=previous is not None,
                    points=unit == "rate",
                ),
            }
        )
    return {
        "rows": rows,
        "weak": weak,
        "has_previous": previous is not None,
        "min_realized": COMPARE_MIN_REALIZED,
        "min_revenue": COMPARE_MIN_REVENUE,
        "previous_label": previous["label"] if previous else "",
    }


def build_trend(reports: list[dict]) -> dict:
    """Tableau + barres SVG (générées côté serveur) du CA sur la fenêtre."""
    rows = [
        {
            "label": r["label"],
            "short": MOIS_FR[r["month"] - 1].capitalize(),
            "revenue": r["revenue"],
            "orders_realized": r["orders_realized"],
            "items_sold": r["items_sold"],
            "average_basket": r["average_basket"],
        }
        for r in reports
    ]
    top = max((r["revenue"] for r in rows), default=0)
    bars = []
    for i, r in enumerate(rows):
        h = round(90 * r["revenue"] / top) if top else 0
        bars.append(
            {
                "x": 30 + i * 90,
                "y": 100 - h,
                "h": h,
                "label_x": 60 + i * 90,
                "value_y": max(100 - h - 4, 10),
                "short": r["short"],
                "revenue": r["revenue"],
            }
        )

    movers: dict[str, list[dict]] = {"up": [], "down": []}
    if len(reports) >= 2:
        first = {p["name"]: p["revenue"] for p in reports[0]["products"]}
        last = {p["name"]: p["revenue"] for p in reports[-1]["products"]}
        deltas = [
            {
                "name": n,
                "delta": last.get(n, 0) - first.get(n, 0),
                "first": first.get(n, 0),
                "last": last.get(n, 0),
            }
            for n in sorted(set(first) | set(last))
        ]
        movers["up"] = sorted(
            (d for d in deltas if d["delta"] > 0), key=lambda d: -d["delta"]
        )[:MOVERS_LIMIT]
        movers["down"] = sorted(
            (d for d in deltas if d["delta"] < 0), key=lambda d: d["delta"]
        )[:MOVERS_LIMIT]
    return {
        "rows": rows,
        "bars": bars,
        "movers": movers,
        "movers_from": reports[0]["label"] if len(reports) >= 2 else "",
        "movers_to": reports[-1]["label"],
    }


def sleeping_products(seller: SellerProfile, year: int, month: int) -> list[dict]:
    """Produits actifs en stock, dans >= 2 ventes du mois (liaison ``FlashSaleProduct``),
    sans aucune vente réalisée sur le mois."""
    start, end = month_bounds(year, month)
    rows = list(
        FlashSaleProduct.objects.filter(
            flash_sale__owner=seller,
            flash_sale__start_time__gte=start,
            flash_sale__start_time__lt=min(end, timezone.now()),
            is_active=True,
            product__is_active=True,
            product__stock_available__gt=0,
        )
        .exclude(flash_sale__status=FlashSaleStatus.CANCELLED)
        .values("product_id", "product__name", "product__stock_available")
        .annotate(n=Count("flash_sale_id", distinct=True))
        .filter(n__gte=SIGNAL_SLEEPING_MIN_SALES)
        .order_by("product__name")
    )
    if not rows:
        return []
    sold = set(
        _collected_items()
        .filter(
            order__flash_sale__owner=seller,
            order__created_at__gte=start,
            order__created_at__lt=end,
            product_id__in=[r["product_id"] for r in rows],
        )
        .values_list("product_id", flat=True)
    )
    return [
        {
            "name": r["product__name"],
            "stock": r["product__stock_available"],
            "sales": r["n"],
        }
        for r in rows
        if r["product_id"] not in sold
    ]


def best_slot(seller: SellerProfile, year: int, month: int) -> dict | None:
    """Créneau de début de vente au meilleur CA par vente (>= 2 créneaux de >= 2 ventes)."""
    start, end = month_bounds(year, month)
    sales = list(
        FlashSale.objects.filter(
            owner=seller, start_time__gte=start, start_time__lt=min(end, timezone.now())
        )
        .exclude(status=FlashSaleStatus.CANCELLED)
        .values_list("pk", "start_time")
    )
    if not sales:
        return None
    revenue_by_sale = dict(
        _collected_items()
        .filter(order__flash_sale_id__in=[pk for pk, _ in sales])
        .values("order__flash_sale_id")
        .annotate(r=Sum(_revenue_expr()))
        .values_list("order__flash_sale_id", "r")
    )
    per_slot: dict[str, list[int]] = defaultdict(list)
    for pk, st in sales:
        per_slot[slot_of(timezone.localtime(st).hour)].append(
            int(revenue_by_sale.get(pk) or 0)
        )
    eligible = {k: v for k, v in per_slot.items() if len(v) >= SIGNAL_SLOT_MIN_SALES}
    if len(eligible) < 2:
        return None
    avg = {k: sum(v) / len(v) for k, v in eligible.items()}
    best = max(avg, key=lambda k: (avg[k], k))
    return {
        "slot": SLOT_LABELS[best],
        "per_sale": round(avg[best]),
        "sales": len(eligible[best]),
    }


def build_signals(report: dict, sleeping: list[dict], slot: dict | None) -> list[dict]:
    """Faits calculés, formulés neutrement (aucun conseil)."""
    out: list[dict] = []

    def add(key: str, text: str) -> None:
        out.append({"key": key, "text": text})

    if report["products"] and report["revenue"]:
        top = report["products"][0]
        if top["share"] > SIGNAL_DEPENDENCE_SHARE:
            add(
                "dependence",
                f"Dépendance : {top['name']} fait {_pct(top['share'])} % des recettes du mois.",
            )
    if sleeping:
        names = ", ".join(f"{p['name']} (stock {p['stock']})" for p in sleeping)
        add(
            "sleeping",
            f"Stock sans vente : {names} — présent(s) dans au moins "
            f"{SIGNAL_SLEEPING_MIN_SALES} ventes du mois, 0 vendu.",
        )
    placed = report["orders_placed"]
    rate = report["realization_rate"]
    if (
        placed >= SIGNAL_DELIVERY_MIN_ORDERS
        and rate is not None
        and rate < SIGNAL_DELIVERY_RATE
    ):
        add(
            "delivery",
            f"Livraisons : taux de réalisation de {rate} % "
            f"({report['orders_realized']} réalisées sur {placed} passées).",
        )
    if report["pending_alert"]:
        add(
            "stale",
            f"Statuts non à jour : {report['orders_stale']} commandes sur {placed} "
            f"({round(report['orders_stale'] / placed * 100)} %) en attente de mise à jour "
            "ou livrées sans paiement encaissé.",
        )
    if slot:
        add(
            "slot",
            f"Meilleur créneau : {slot['slot']}, {_fmt(slot['per_sale'])} FCFA "
            f"de CA par vente ({slot['sales']} ventes).",
        )
    if report["customers"] >= SIGNAL_LOYAL_MIN_CUSTOMERS:
        share = round(report["customers_returning"] / report["customers"] * 100)
        add(
            "loyal",
            f"Clientes fidèles : {share} % des clientes du mois "
            f"({report['customers_returning']} sur {report['customers']}) "
            "avaient déjà commandé avant.",
        )
    if report["sales_count"] == 0:
        add("inactive", "Inactivité : aucune vente flash ce mois.")
    return out


def shop_bilan(seller: SellerProfile, year: int, month: int) -> dict:
    """Fiche complète : mois, comparaison, évolution, signaux, résumé texte."""
    reg = timezone.localtime(seller.created_at)
    first = (reg.year, reg.month)
    window: list[tuple[int, int]] = []
    ym = (year, month)
    for _ in range(TREND_MONTHS):
        if ym < first:
            break
        window.append(ym)
        ym = previous_month(*ym)
    window.reverse()
    reports = [shop_month_report(seller, y, m) for y, m in window]
    report = reports[-1]
    previous = reports[-2] if len(reports) > 1 else None
    sleeping = sleeping_products(seller, year, month)
    bilan = {
        "report": report,
        "previous": previous,
        "comparison": build_comparison(report, previous),
        "trend": build_trend(reports),
        "sleeping": sleeping,
        "signals": build_signals(report, sleeping, best_slot(seller, year, month)),
        "months_since_signup": max((year * 12 + month) - (first[0] * 12 + first[1]), 0),
    }
    bilan["summary"] = build_text_summary(seller, bilan)
    return bilan


def _cmp_text(row: dict, comp: dict, *, suffix: str = "") -> str:
    """« (mois précédent : X, +28 %) » selon la règle du seuil."""
    if not comp["has_previous"]:
        return ""
    v = row["variation"]
    prev = f"{_fmt(row['previous'])}{suffix}"
    if v["state"] == "weak":
        return f" (mois précédent : {prev}, base trop faible pour comparer)"
    if v["state"] == "ok" and v["pct"] is not None:
        return f" (mois précédent : {prev}, {v['pct']:+d} %)"
    return f" (mois précédent : {prev})"


def build_text_summary(seller: SellerProfile, bilan: dict) -> str:
    """Résumé texte compact : aucune donnée acheteur, aucun téléphone."""
    r = bilan["report"]
    comp = bilan["comparison"]
    by_key = {row["key"]: row for row in comp["rows"]}
    name = seller.business_name or seller.user.display_name
    rate = f" ({r['realization_rate']} %)" if r["realization_rate"] is not None else ""
    top = ", ".join(f"{p['name']} {_pct(p['share'])} %" for p in r["products"][:3]) or "—"
    sleeping = ", ".join(
        f"{p['name']} (stock {p['stock']})" for p in bilan["sleeping"]
    ) or "aucun"
    months = " | ".join(
        f"{row['short']} {_fmt(row['revenue'])}" for row in bilan["trend"]["rows"]
    )
    signals = " ; ".join(s["text"] for s in bilan["signals"]) or "aucun"
    lines = [
        f"BILAN HAYAFLASH — Boutique : {name} — {r['label'].capitalize()}",
        (
            f"Catégorie : {seller.get_category_display() or '—'} | "
            f"Plan : {effective_plan(seller).upper()} | "
            f"Inscrite depuis : {bilan['months_since_signup']} mois"
        ),
        f"Ventes flash : {r['sales_count']}"
        + (
            f" (mois précédent : {by_key['sales_count']['previous']})"
            if comp["has_previous"]
            else ""
        ),
        (
            f"Commandes : {r['orders_placed']} passées, "
            f"{r['orders_realized']} réalisées{rate}, "
            f"{r['orders_cancelled']} annulées, {r['orders_stale']} non mises à jour"
        ),
        f"CA réalisé : {_fmt(r['revenue'])} FCFA"
        + _cmp_text(by_key["revenue"], comp, suffix=" FCFA"),
        f"Panier moyen : {_fmt(r['average_basket'])} FCFA",
        f"Top produits (% des recettes) : {top}",
        f"Produits sans vente : {sleeping}",
        f"3 derniers mois (CA) : {months}",
        f"Signaux : {signals}",
    ]
    return "\n".join(lines)
