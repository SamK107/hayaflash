from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from accounts.models import SellerProfile
from analytics.aggregators.seller_stats import get_seller_public_stats
from analytics.services.cache import flash_page_version_key, get_page_version, seller_page_version_key
from analytics.services.seo import compute_page_etag
from analytics.services.share_links import (
    absolute_url,
    build_order_share_urls,
    build_tracked_whatsapp_url,
    build_whatsapp_message,
    build_whatsapp_urls,
    flash_sale_public_path,
    get_or_create_flash_sale_share_link,
    get_or_create_seller_share_link,
    seller_public_path,
)
from flash_sales.models import FlashSale


def _seller_display_name(profile: SellerProfile) -> str:
    return (profile.business_name or profile.user.display_name or "Vendeur").strip()


def resolve_seller_public_page(request: HttpRequest, slug: str) -> dict[str, Any]:
    cleaned = (slug or "").strip().lower()
    if not cleaned or len(cleaned) > 80:
        return {"not_found": True}

    seller = (
        SellerProfile.objects.filter(public_slug=cleaned, is_active=True)
        .select_related("user")
        .only(
            "id",
            "public_slug",
            "business_name",
            "user__display_name",
            "updated_at",
        )
        .first()
    )
    if seller is None:
        return {"not_found": True}

    version = get_page_version(seller_page_version_key(cleaned))
    stats = get_seller_public_stats(seller.pk)
    now = timezone.now()
    active_sales = list(
        FlashSale.objects.filter(
            owner_id=seller.pk,
            start_time__lte=now,
            end_time__gte=now,
        )
        .only("id", "title", "public_slug", "start_time", "end_time")
        .order_by("-start_time")[:12]
    )

    share_link = get_or_create_seller_share_link(seller=seller)
    seller_path = seller_public_path(seller.public_slug)
    seller_url = absolute_url(request, seller_path)
    wa = build_whatsapp_urls(
        message=build_whatsapp_message(
            headline=f"Boutique {_seller_display_name(seller)} sur HayaFlash",
            url=seller_url,
        )
    )
    whatsapp_tracked = build_tracked_whatsapp_url(
        request,
        share_token=share_link.token,
        whatsapp_url=wa["mobile"],
        source="whatsapp",
    )

    etag = compute_page_etag(
        slug=cleaned,
        version=version,
        extra=f"{stats['total_orders']}:{len(active_sales)}",
    )

    return {
        "not_found": False,
        "seller_name": _seller_display_name(seller),
        "seller_slug": seller.public_slug,
        "seller_id": seller.pk,
        "active_sales": active_sales,
        "total_orders": stats["total_orders"],
        "products_sold": stats["products_sold"],
        "seller_url": seller_url,
        "whatsapp_url": whatsapp_tracked,
        "whatsapp_mobile_url": wa["mobile"],
        "whatsapp_desktop_url": wa["desktop"],
        "share_link": share_link,
        "share_token": share_link.token,
        "page_etag": etag,
        "page_version": version,
    }


def resolve_flash_sale_public_page(request: HttpRequest, slug: str) -> dict[str, Any]:
    cleaned = (slug or "").strip().lower()
    if not cleaned or len(cleaned) > 80:
        return {"not_found": True}

    flash_sale = (
        FlashSale.objects.filter(public_slug=cleaned)
        .select_related("owner__user")
        .prefetch_related("products", "products__media")
        .first()
    )
    if flash_sale is None:
        return {"not_found": True}

    version = get_page_version(flash_page_version_key(cleaned))
    share_link = get_or_create_flash_sale_share_link(flash_sale=flash_sale)
    products = list(flash_sale.products.all())
    flash_path = flash_sale_public_path(flash_sale.public_slug)
    flash_url = absolute_url(request, flash_path)
    wa = build_whatsapp_urls(
        message=build_whatsapp_message(headline=flash_sale.title, url=flash_url)
    )
    whatsapp_tracked = build_tracked_whatsapp_url(
        request,
        share_token=share_link.token,
        whatsapp_url=wa["mobile"],
        source="whatsapp",
    )

    product_links: list[dict[str, Any]] = []
    for product in products:
        urls = build_order_share_urls(request, flash_sale=flash_sale, product=product)
        product_wa = build_whatsapp_urls(message=urls["whatsapp_message"])
        product_links.append(
            {
                "product": product,
                "order_url": urls["order_url"],
                "whatsapp_url": build_tracked_whatsapp_url(
                    request,
                    share_token=urls["share_token"],
                    whatsapp_url=product_wa["mobile"],
                    source="whatsapp",
                ),
                "whatsapp_mobile_url": product_wa["mobile"],
                "whatsapp_desktop_url": product_wa["desktop"],
                "share_token": urls["share_token"],
            }
        )

    is_live = flash_sale.is_live()
    teasers_list = [t.strip() for t in (flash_sale.teasers or "").splitlines() if t.strip()]
    open_ts_ms = int(flash_sale.start_time.timestamp() * 1000)
    etag = compute_page_etag(
        slug=cleaned,
        version=version,
        extra=f"{is_live}:{len(products)}",
    )

    return {
        "not_found": False,
        "flash_sale": flash_sale,
        "seller_name": _seller_display_name(flash_sale.owner),
        "seller_slug": flash_sale.owner.public_slug,
        "seller_id": flash_sale.owner_id,
        "is_live": is_live,
        "open_ts_ms": open_ts_ms,
        "teasers_list": teasers_list,
        "product_count": len(products),
        "products": products,
        "product_links": product_links,
        "flash_sale_url": flash_url,
        "seller_url": absolute_url(request, seller_public_path(flash_sale.owner.public_slug)),
        "whatsapp_url": whatsapp_tracked,
        "whatsapp_mobile_url": wa["mobile"],
        "whatsapp_desktop_url": wa["desktop"],
        "share_link": share_link,
        "share_token": share_link.token,
        "page_etag": etag,
        "page_version": version,
    }


def build_referral_loop_context(
    request: HttpRequest,
    *,
    flash_sale_id: int,
    product_id: int,
    order_id: int | None = None,
) -> dict[str, Any]:
    flash_sale = (
        FlashSale.objects.filter(pk=flash_sale_id)
        .select_related("owner__user")
        .prefetch_related("products", "products__media")
        .first()
    )
    if flash_sale is None:
        return {"available": False}

    product = next((p for p in flash_sale.products.all() if p.pk == product_id), None)
    if product is None:
        return {"available": False}

    share = build_order_share_urls(request, flash_sale=flash_sale, product=product)
    now = timezone.now()
    other_sales = list(
        FlashSale.objects.filter(
            owner_id=flash_sale.owner_id,
            start_time__lte=now,
            end_time__gte=now,
        )
        .exclude(pk=flash_sale.pk)
        .only("id", "title", "public_slug")
        .order_by("-start_time")[:6]
    )

    invite_wa = build_whatsapp_urls(
        message=build_whatsapp_message(
            headline=f"Je viens de commander sur HayaFlash — {product.name} !",
            url=share["order_url"],
        )
    )
    product_wa = build_whatsapp_urls(message=share["whatsapp_message"])

    return {
        "available": True,
        "order_id": order_id,
        "product_name": product.name,
        "flash_sale_title": flash_sale.title,
        "seller_name": _seller_display_name(flash_sale.owner),
        "seller_url": share["seller_url"],
        "order_url": share["order_url"],
        "whatsapp_url": product_wa["mobile"],
        "whatsapp_invite_url": invite_wa["mobile"],
        "share_token": share["share_token"],
        "other_sales": other_sales,
    }
