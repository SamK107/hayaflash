"""Vitrine du Marche (/ventes/) : produit vedette, vignettes, « Produits du moment ».

Lecture seule, calculee en lot (3 requetes quel que soit le nombre de ventes et
de produits) et mise en cache avec le snapshot du Marche (30 s). Ne contient que
des types simples (pas d'instances de modele).

Regles :
- jamais de produit inactif, retire de la vente ou en rupture (stock <= 0) ;
- images : miniatures WebP uniquement (200 px / 480 px), jamais l'original ;
- prix = prix promo de la vente s'il existe, sinon prix catalogue (FCFA entiers) ;
  pastille « -X % » seulement si promo < prix catalogue ;
- aucun chiffre de commande n'est expose : le classement s'en sert, pas l'affichage.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count
from django.utils import timezone

from core.services.thumbnails import THUMB_MAIN, THUMB_SMALL, get_thumbnail

THUMBS_PER_SALE = 3
MOMENT_MAX = 12
MOMENT_PER_SHOP = 2
PLACEHOLDER_COLORS = 6


def _initials(name: str) -> str:
    words = [w for w in name.replace("-", " ").split() if w]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def _discount(link) -> int | None:
    catalogue, promo = link.product.price, link.promo_price
    if promo is not None and catalogue > 0 and promo < catalogue:
        return max(1, round(100 * (catalogue - promo) / catalogue))
    return None


def _product_dict(link, image_file, *, size: int) -> dict[str, Any]:
    product = link.product
    discount = _discount(link)
    promo = link.promo_price
    return {
        "id": product.pk,
        "name": product.name,
        "price": int(promo) if promo is not None else int(product.price),
        "old_price": int(product.price) if discount else None,
        "discount": discount,
        "image": get_thumbnail(image_file, size) if image_file else None,
        "initials": _initials(product.name),
        "ph": product.pk % PLACEHOLDER_COLORS,
    }


def build_showcase(live_sales, other_ids, now=None) -> tuple[dict[int, dict], list[dict]]:
    """``(showcase, moment)``.

    ``showcase`` : {id vente -> {"main", "thumbs", "more", "count"}} pour les
    ventes en direct (``main`` = produit vedette, grande image), a venir et
    terminees (``main`` = None, apercu de 3 vignettes). ``moment`` : jusqu'a 12
    produits des ventes en direct (les plus commandes aujourd'hui, puis les plus
    fortes promos, puis l'ordre d'affichage ; 2 par boutique au plus).
    """
    from orders.models import OrderItem, OrderStatus
    from products.models import FlashSaleProduct, ProductMedia

    now = now or timezone.now()
    live_by_id = {s.pk: s for s in live_sales}
    all_ids = list(live_by_id) + [i for i in other_ids if i not in live_by_id]
    if not all_ids:
        return {}, []

    links = list(
        FlashSaleProduct.objects.filter(
            flash_sale_id__in=all_ids, is_active=True, product__is_active=True,
            product__stock_available__gt=0,
        )
        .select_related("product")
        .order_by("flash_sale_id", "display_order", "-created_at")
    )
    by_sale: dict[int, list] = {}
    for link in links:
        by_sale.setdefault(link.flash_sale_id, []).append(link)

    first_image: dict[int, Any] = {}
    for media in (
        ProductMedia.objects.filter(
            product_id__in={link.product_id for link in links},
            media_type=ProductMedia.MediaType.IMAGE, file__isnull=False,
        )
        .exclude(file="")
        .order_by("product_id", "order", "id")
    ):
        first_image.setdefault(media.product_id, media.file)

    showcase: dict[int, dict] = {}
    for sale_id in all_ids:
        sale_links = by_sale.get(sale_id, [])
        main_link = None
        if sale_id in live_by_id and sale_links:
            # Vedette : premier produit avec image (et du stock), sinon le premier.
            main_link = next((lk for lk in sale_links if lk.product_id in first_image), sale_links[0])
        rest = [lk for lk in sale_links if lk is not main_link]
        thumbs = rest[:THUMBS_PER_SALE]
        showcase[sale_id] = {
            "main": (
                _product_dict(main_link, first_image.get(main_link.product_id), size=THUMB_MAIN)
                if main_link else None
            ),
            "thumbs": [
                _product_dict(lk, first_image.get(lk.product_id), size=THUMB_SMALL) for lk in thumbs
            ],
            "more": max(0, len(rest) - len(thumbs)),
            "count": len(sale_links),
        }

    # ── Produits du moment ───────────────────────────────────────────
    day_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    ordered = {
        row["product_id"]: row["n"]
        for row in OrderItem.objects.filter(
            order__flash_sale_id__in=list(live_by_id), order__created_at__gte=day_start
        )
        .exclude(order__status=OrderStatus.CANCELLED)
        .values("product_id")
        .annotate(n=Count("order_id", distinct=True))
    }
    candidates = []
    live_links = [lk for sale_id in live_by_id for lk in by_sale.get(sale_id, [])]
    for position, link in enumerate(live_links):
        candidates.append((-ordered.get(link.product_id, 0), -(_discount(link) or 0), position, link))
    candidates.sort(key=lambda c: c[:3])

    moment: list[dict] = []
    seen_products: set[int] = set()
    per_shop: dict[int, int] = {}
    for _orders, _promo, _pos, link in candidates:
        sale = live_by_id[link.flash_sale_id]
        if link.product_id in seen_products or per_shop.get(sale.owner_id, 0) >= MOMENT_PER_SHOP:
            continue
        item = _product_dict(link, first_image.get(link.product_id), size=THUMB_SMALL)
        item.update(
            sale_id=sale.pk, slug=sale.public_slug, end_time=sale.end_time,
            shop_name=sale.owner.business_name, category=sale.effective_category,
        )
        moment.append(item)
        seen_products.add(link.product_id)
        per_shop[sale.owner_id] = per_shop.get(sale.owner_id, 0) + 1
        if len(moment) >= MOMENT_MAX:
            break
    return showcase, moment
