from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from analytics.models import ShareLink, ShareLinkType


def get_public_base_url(request: HttpRequest | None = None) -> str:
    configured = (getattr(settings, "HAYAFLASH_PUBLIC_BASE_URL", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return ""


def seller_public_path(slug: str) -> str:
    return reverse("public_seller", kwargs={"slug": slug})


def flash_sale_public_path(slug: str) -> str:
    return reverse("public_flash_sale", kwargs={"slug": slug})


def order_page_path(*, flash_sale_id: int, product_id: int, ref: str = "") -> str:
    base = reverse("client_order")
    qs = f"flash_sale_id={flash_sale_id}&product_id={product_id}"
    if ref:
        qs += f"&ref={quote(ref, safe='')}"
    return f"{base}?{qs}"


def absolute_url(request: HttpRequest | None, path: str) -> str:
    base = get_public_base_url(request)
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def get_or_create_seller_share_link(*, seller) -> ShareLink:
    key = f"seller:{seller.pk}"
    link = ShareLink.objects.filter(target_key=key).first()
    if link:
        return link
    link = ShareLink(
        link_type=ShareLinkType.SELLER,
        seller=seller,
        target_key=key,
    )
    link.save()
    return link


def get_or_create_flash_sale_share_link(*, flash_sale) -> ShareLink:
    key = f"flash_sale:{flash_sale.pk}"
    link = ShareLink.objects.filter(target_key=key).first()
    if link:
        return link
    link = ShareLink(
        link_type=ShareLinkType.FLASH_SALE,
        seller=flash_sale.owner,
        flash_sale=flash_sale,
        target_key=key,
    )
    link.save()
    return link


def get_or_create_product_share_link(*, flash_sale, product) -> ShareLink:
    key = f"product:{product.pk}"
    link = ShareLink.objects.filter(target_key=key).first()
    if link:
        return link
    link = ShareLink(
        link_type=ShareLinkType.PRODUCT,
        seller=flash_sale.owner,
        flash_sale=flash_sale,
        product=product,
        target_key=key,
    )
    link.save()
    return link


def build_whatsapp_message(*, headline: str, url: str) -> str:
    lines = [
        "🔥 Vente Flash en cours sur HayaFlash !",
        headline.strip(),
        f"Commandez : {url}",
        "",
        "Powered by HayaFlash",
    ]
    return "\n".join(lines)


def build_whatsapp_share_url(*, message: str) -> str:
    return build_whatsapp_urls(message=message)["mobile"]


def build_whatsapp_urls(*, message: str) -> dict[str, str]:
    encoded = quote(message, safe="")
    return {
        "mobile": f"https://wa.me/?text={encoded}",
        "desktop": f"https://api.whatsapp.com/send?text={encoded}",
    }


def validate_whatsapp_redirect_target(target: str) -> bool:
    if not target:
        return False
    return target.startswith("https://wa.me/") or target.startswith(
        "https://api.whatsapp.com/send"
    )


def build_tracked_whatsapp_url(
    request: HttpRequest | None,
    *,
    share_token: str,
    whatsapp_url: str,
    source: str = "whatsapp",
) -> str:
    from urllib.parse import quote

    track_path = reverse("track_whatsapp_share")
    qs = (
        f"ref={quote(share_token, safe='')}"
        f"&to={quote(whatsapp_url, safe='')}"
        f"&src={quote(source, safe='')}"
    )
    return absolute_url(request, f"{track_path}?{qs}")


def build_order_share_urls(
    request: HttpRequest | None,
    *,
    flash_sale,
    product,
) -> dict[str, str]:
    share_link = get_or_create_product_share_link(
        flash_sale=flash_sale,
        product=product,
    )
    order_path = order_page_path(
        flash_sale_id=flash_sale.pk,
        product_id=product.pk,
        ref=share_link.token,
    )
    order_url = absolute_url(request, order_path)
    flash_path = flash_sale_public_path(flash_sale.public_slug)
    flash_url = absolute_url(request, flash_path)
    seller_path = seller_public_path(flash_sale.owner.public_slug)
    seller_url = absolute_url(request, seller_path)
    message = build_whatsapp_message(
        headline=f"{flash_sale.title} — {product.name}",
        url=order_url,
    )
    return {
        "share_token": share_link.token,
        "order_url": order_url,
        "flash_sale_url": flash_url,
        "seller_url": seller_url,
        "whatsapp_url": build_whatsapp_share_url(message=message),
        "whatsapp_mobile_url": build_whatsapp_urls(message=message)["mobile"],
        "whatsapp_desktop_url": build_whatsapp_urls(message=message)["desktop"],
        "whatsapp_message": message,
    }
