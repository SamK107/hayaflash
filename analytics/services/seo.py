from __future__ import annotations

import hashlib
import json
from typing import Any

from django.http import HttpRequest

from analytics.services.share_links import absolute_url


def build_seller_seo(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    title = f"{context['seller_name']} — HayaFlash"
    description = (
        f"Boutique {context['seller_name']} sur HayaFlash. "
        f"{context['total_orders']} commandes · ventes flash en direct."
    )
    canonical = context["seller_url"]
    og_image = absolute_url(request, "/static/orders/img/hayaflash-og.png")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Store",
        "name": context["seller_name"],
        "url": canonical,
        "description": description,
        "brand": {"@type": "Brand", "name": "HayaFlash"},
    }
    return _seo_bundle(
        title=title,
        description=description,
        canonical=canonical,
        og_image=og_image,
        json_ld=json_ld,
    )


def build_flash_sale_seo(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    sale = context["flash_sale"]
    title = f"{sale.title} — HayaFlash"
    description = (
        f"Vente flash {sale.title} par {context['seller_name']}. "
        "Commandez en direct sur HayaFlash."
    )
    canonical = context["flash_sale_url"]
    og_image = absolute_url(request, "/static/orders/img/hayaflash-og.png")
    offers = []
    for product in context.get("products", []):
        offers.append(
            {
                "@type": "Offer",
                "itemOffered": {
                    "@type": "Product",
                    "name": product.name,
                    "offers": {
                        "@type": "Offer",
                        "price": str(product.price),
                        "priceCurrency": "XOF",
                        "availability": "https://schema.org/InStock"
                        if product.stock_available > 0 and context.get("is_live")
                        else "https://schema.org/OutOfStock",
                    },
                },
            }
        )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "OfferCatalog",
        "name": sale.title,
        "url": canonical,
        "seller": {"@type": "Organization", "name": context["seller_name"]},
        "itemListElement": offers,
    }
    return _seo_bundle(
        title=title,
        description=description,
        canonical=canonical,
        og_image=og_image,
        json_ld=json_ld,
    )


def compute_page_etag(*, slug: str, version: int, extra: str = "") -> str:
    raw = f"{slug}:{version}:{extra}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _seo_bundle(
    *,
    title: str,
    description: str,
    canonical: str,
    og_image: str,
    json_ld: dict,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "canonical_url": canonical,
        "og": {
            "title": title,
            "description": description,
            "url": canonical,
            "image": og_image,
            "type": "website",
            "site_name": "HayaFlash",
        },
        "twitter": {
            "card": "summary_large_image",
            "title": title,
            "description": description,
            "image": og_image,
        },
        "json_ld": json.dumps(json_ld, ensure_ascii=False),
    }
