from __future__ import annotations

import time
from collections.abc import Callable

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from accounts.models import SellerProfile
from orders.services.client_order import resolve_client_order_page
from orders.services.dashboard import (
    advance_order_status,
    get_dashboard_kpis_cached,
    get_order_row_context,
    list_dashboard_order_rows,
)

PARTIAL_MIN_INTERVAL_SECONDS = 3.0


@require_GET
def client_order_page(request):
    """Public quick-order page."""
    context = resolve_client_order_page(request)
    return render(request, "orders/client_order.html", context)


def _require_seller(user):
    if not user.is_authenticated:
        return False
    return SellerProfile.objects.filter(user=user, is_active=True).exists()


def _rate_limited_partial_html(
    request,
    *,
    slot: str,
    build_html: Callable[[], str],
) -> HttpResponse:
    uid = request.user.pk
    now = time.time()
    tkey = f"dash:{uid}:t:{slot}"
    hkey = f"dash:{uid}:h:{slot}"
    last = cache.get(tkey)
    if last is not None and (now - float(last)) < PARTIAL_MIN_INTERVAL_SECONDS:
        cached = cache.get(hkey)
        if isinstance(cached, str) and cached:
            return HttpResponse(cached, content_type="text/html; charset=utf-8")
    html = build_html()
    cache.set(tkey, now, 30)
    cache.set(hkey, html, 30)
    return HttpResponse(html, content_type="text/html; charset=utf-8")


@login_required
def seller_dashboard(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")
    from flash_sales.models import FlashSale, FlashSaleStatus
    seller = request.user.seller_profile
    live_sale = (
        FlashSale.objects.filter(owner=seller, status=FlashSaleStatus.LIVE)
        .order_by("-start_time")
        .first()
    )
    next_sale = None
    if not live_sale:
        next_sale = (
            FlashSale.objects.filter(owner=seller, status=FlashSaleStatus.SCHEDULED)
            .order_by("start_time")
            .first()
        )
    return render(request, "orders/dashboard.html", {
        "live_sale": live_sale,
        "next_sale": next_sale,
    })


@login_required
def seller_dashboard_kpi_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    def build() -> str:
        return render_to_string(
            "orders/partials/kpi.html",
            {"kpis": get_dashboard_kpis_cached(request.user)},
            request=request,
        )

    return _rate_limited_partial_html(request, slot="kpi", build_html=build)


@login_required
def seller_dashboard_orders_partial(request):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")

    def build() -> str:
        return render_to_string(
            "orders/partials/orders_list.html",
            {"order_rows": list_dashboard_order_rows(request.user)},
            request=request,
        )

    return _rate_limited_partial_html(request, slot="orders", build_html=build)


@login_required
@require_POST
def seller_order_advance_status(request, order_id: int):
    if not _require_seller(request.user):
        return HttpResponseForbidden("Seller profile required.")
    try:
        advance_order_status(user=request.user, order_id=order_id)
    except PermissionDenied:
        return HttpResponseForbidden("Not allowed.")
    except ValidationError as exc:
        msg = "; ".join(getattr(exc, "messages", [])) or str(exc)
        return HttpResponse(msg, status=400)

    row = get_order_row_context(request.user, order_id)
    if row is None:
        return HttpResponseForbidden("Order not found.")
    html = render_to_string(
        "orders/partials/order_row.html",
        {"row": row},
        request=request,
    )
    return HttpResponse(html, content_type="text/html; charset=utf-8")
