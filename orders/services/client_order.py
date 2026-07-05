from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpRequest

from accounts.services.users import normalize_phone
from analytics.services.share_links import build_order_share_urls
from analytics.services.tracking import (
    normalize_tracking_source,
    record_conversion_for_order,
    record_page_view,
    resolve_share_link_by_token,
)
from delivery.services.validation import validate_delivery_input
from flash_sales.models import FlashSale
from flash_sales.services.ordering import assert_flash_sale_accepts_orders
from orders.models import Order
from orders.services.create_order import create_order
from products.models import Product

ORDER_SUBMIT_RATE_WINDOW_SECONDS = 60
ORDER_SUBMIT_RATE_MAX_PER_WINDOW = 30


def _client_ip(request: HttpRequest) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]


def enforce_public_order_rate_limit(request: HttpRequest) -> None:
    """Soft per-IP limit on order submissions (shared cache: LocMem or Redis)."""
    ip = _client_ip(request)
    key = f"order_submit_ip:{ip}"
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, ORDER_SUBMIT_RATE_WINDOW_SECONDS)
        n = 1
    if n > ORDER_SUBMIT_RATE_MAX_PER_WINDOW:
        raise ValidationError(
            {
                "detail": (
                    "Too many order attempts from this network. "
                    "Please wait a minute and try again."
                )
            }
        )


def _as_positive_int(value: Any, field: str, *, min_value: int = 1) -> int:
    if isinstance(value, bool):
        raise ValidationError({field: "Invalid integer."})
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.strip().isdigit():
        n = int(value.strip())
    else:
        raise ValidationError({field: "Must be a positive integer."})
    if n < min_value:
        raise ValidationError({field: f"Must be at least {min_value}."})
    return n


def _extract_delivery_from_public(data: dict[str, Any]) -> dict[str, Any]:
    """Map public body delivery fields (nested or legacy top-level address_text)."""
    raw = data.get("delivery")
    if isinstance(raw, dict):
        return validate_delivery_input(raw)

    legacy_address = data.get("address_text")
    if isinstance(legacy_address, str) and legacy_address.strip():
        return validate_delivery_input(
            {
                "address_text": legacy_address,
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "geo_accuracy": data.get("geo_accuracy"),
                "geo_method": data.get("geo_method") or "manual",
                "delivery_notes": data.get("delivery_notes") or "",
            }
        )

    raise ValidationError({"delivery": "This field is required."})


def build_create_order_payload_from_public(*, data: dict[str, Any]) -> dict[str, Any]:
    """
    Map public API / form body to ``create_order`` payload.
    Required: flash_sale_id, product_id, name, phone, quantity, client_request_id.
    """
    if not isinstance(data, dict):
        raise ValidationError({"detail": "Body must be a JSON object."})

    missing = [
        k
        for k in (
            "flash_sale_id",
            "product_id",
            "name",
            "phone",
            "quantity",
            "client_request_id",
        )
        if k not in data
    ]
    if missing:
        raise ValidationError(
            {m: "This field is required." for m in missing},
        )

    flash_sale_id = _as_positive_int(data["flash_sale_id"], "flash_sale_id")
    product_id = _as_positive_int(data["product_id"], "product_id")
    quantity = _as_positive_int(data["quantity"], "quantity")

    if not isinstance(data["name"], str) or not data["name"].strip():
        raise ValidationError({"name": "Must be a non-empty string."})
    if not isinstance(data["phone"], str) or not data["phone"].strip():
        raise ValidationError({"phone": "Must be a non-empty string."})
    if not isinstance(data["client_request_id"], str) or not data["client_request_id"].strip():
        raise ValidationError({"client_request_id": "Must be a non-empty string."})

    try:
        phone_norm = normalize_phone(data["phone"])
    except TypeError as exc:
        raise ValidationError({"phone": "Invalid phone value."}) from exc

    flash_sale = FlashSale.objects.filter(pk=flash_sale_id).first()
    if flash_sale is None:
        raise ValidationError({"flash_sale_id": "Flash sale not found."})

    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        raise ValidationError({"product_id": "Product not found."})
    if product.flash_sale_id != flash_sale.id:
        raise ValidationError(
            {"product_id": "This product is not part of the selected flash sale."}
        )

    assert_flash_sale_accepts_orders(flash_sale)

    delivery = _extract_delivery_from_public(data)

    return {
        "flash_sale_id": flash_sale_id,
        "customer_name": data["name"].strip(),
        "customer_phone": phone_norm,
        "client_request_id": data["client_request_id"].strip()[:128],
        "items": [{"product_id": product_id, "quantity": quantity}],
        "delivery": delivery,
    }


def resolve_client_order_page(request: HttpRequest) -> dict[str, Any]:
    """
    Context for GET /order/ (flash sale + product from query string).
    """
    raw_fs = request.GET.get("flash_sale_id") or request.GET.get("flash_sale")
    raw_pr = request.GET.get("product_id") or request.GET.get("product")
    if not raw_fs or not raw_pr:
        return {
            "page_error": "Ajoutez flash_sale_id et product_id dans l’URL (ex. ?flash_sale_id=1&product_id=1).",
            "flash_sale_id": "",
            "product_id": "",
            "product_name": "",
            "flash_sale_title": "",
            "can_submit": False,
        }
    try:
        flash_sale_id = int(raw_fs)
        product_id = int(raw_pr)
    except (TypeError, ValueError):
        return {
            "page_error": "flash_sale_id et product_id doivent être des entiers valides.",
            "flash_sale_id": "",
            "product_id": "",
            "product_name": "",
            "flash_sale_title": "",
            "can_submit": False,
        }

    flash_sale = FlashSale.objects.filter(pk=flash_sale_id).select_related("owner__user").first()
    product = Product.objects.filter(pk=product_id).select_related("flash_sale").prefetch_related("media").first()
    if flash_sale is None or product is None:
        return {
            "page_error": "Vente flash ou produit introuvable.",
            "flash_sale_id": str(flash_sale_id),
            "product_id": str(product_id),
            "product_name": "",
            "flash_sale_title": "",
            "can_submit": False,
        }
    if product.flash_sale_id != flash_sale.id:
        return {
            "page_error": "Ce produit n’appartient pas à cette vente flash.",
            "flash_sale_id": str(flash_sale_id),
            "product_id": str(product_id),
            "product_name": product.name,
            "flash_sale_title": flash_sale.title,
            "can_submit": False,
        }

    try:
        assert_flash_sale_accepts_orders(flash_sale)
        can_submit = True
        page_error = ""
    except ValidationError as exc:
        can_submit = False
        msgs = getattr(exc, "message_dict", None) or {}
        flat = []
        for v in msgs.values():
            if isinstance(v, list):
                flat.extend(v)
            else:
                flat.append(str(v))
        page_error = flat[0] if flat else "La vente n’accepte pas les commandes pour le moment."

    return {
        "page_error": page_error,
        "flash_sale_id": str(flash_sale_id),
        "product_id": str(product_id),
        "product_name": product.name,
        "flash_sale_title": flash_sale.title,
        "can_submit": can_submit,
        "share_ref": _resolve_share_ref(request),
        "tracking_source": normalize_tracking_source(request.GET.get("src")),
        "share_urls": build_order_share_urls(
            request,
            flash_sale=flash_sale,
            product=product,
        ),
        "seller_slug": flash_sale.owner.public_slug,
        "flash_sale_slug": flash_sale.public_slug,
        # Objets complets pour le template Tailwind
        "product": product,
        "flash_sale": flash_sale,
    }


def _resolve_share_ref(request: HttpRequest) -> str:
    raw = (request.GET.get("ref") or "").strip().lower()
    if not raw:
        return ""
    link = resolve_share_link_by_token(raw)
    if link is None:
        return ""
    record_page_view(
        request,
        share_link=link,
        source=normalize_tracking_source(request.GET.get("src")),
    )
    return link.token


def submit_public_order_api(request: HttpRequest, data: dict[str, Any]) -> tuple[Order, bool]:
    """
    Validate, rate-limit, then delegate to ``create_order`` (single persistence path).
    Returns (order, created_new).
    """
    enforce_public_order_rate_limit(request)
    payload = build_create_order_payload_from_public(data=data)
    created_new = not Order.service_objects.filter(
        client_request_id=payload["client_request_id"]
    ).exists()
    order = create_order(payload)
    if created_new:
        share_token = data.get("share_ref") or data.get("ref")
        source = normalize_tracking_source(data.get("src"))
        record_conversion_for_order(
            request,
            share_token=str(share_token) if share_token else None,
            order=order,
            source=source,
        )
    return order, created_new
